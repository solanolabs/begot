// Copyright (c) 2014-2015 Solano Labs Inc.  All Rights Reserved.

package main

import (
	"bytes"
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"go/parser"
	"go/token"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"syscall"

	"gopkg.in/yaml.v2"
)

const (
	BEGOTTEN      = "Begotten"
	BEGOTTEN_LOCK = "Begotten.lock"

	DEFAULT_BRANCH = "master"

	EMPTY_DEP = "_begot_empty_dep"
	FLOAT     = "_begot_float"

	// This should change if the format of Begotten.lock changes in an incompatible
	// way. (But prefer changing it in compatible ways and not incrementing this.)
	FILE_VERSION = 2
)

// Known public servers and how many path components form the repo name.
var KNOWN_GIT_SERVERS = map[string]int{
	"github.com":    2,
	"bitbucket.org": 2,
	"begot.test":    2,
}

var RE_NON_IDENTIFIER_CHAR = regexp.MustCompile("\\W")

func replace_non_identifier_chars(in string) string {
	return RE_NON_IDENTIFIER_CHAR.ReplaceAllLiteralString(in, "_")
}

func Command(cwd string, name string, args ...string) (cmd *exec.Cmd) {
	cmd = exec.Command(name, args...)
	cmd.Dir = cwd
	return
}

func cc(cwd string, name string, args ...string) {
	cmd := Command(cwd, name, args...)
	if err := cmd.Run(); err != nil {
		panic(fmt.Errorf("command '%s %s' in %s: %s", name, strings.Join(args, " "), cwd, err))
	}
}

func co(cwd string, name string, args ...string) string {
	cmd := Command(cwd, name, args...)
	if outb, err := cmd.Output(); err != nil {
		panic(fmt.Errorf("command '%s %s' in %s: %s", name, strings.Join(args, " "), cwd, err))
	} else {
		return string(outb)
	}
}

func contains_str(lst []string, val string) bool {
	for _, item := range lst {
		if item == val {
			return true
		}
	}
	return false
}

func sha1str(in string) string {
	sum := sha1.Sum([]byte(in))
	return hex.EncodeToString(sum[:])
}

func sha1bts(in []byte) string {
	sum := sha1.Sum(in)
	return hex.EncodeToString(sum[:])
}

func implicit_name(git_url, subpath string) string {
	return "_begot_" + sha1str(git_url+"/"+subpath)
}

func realpath(path string) (out string) {
	if abs, err := filepath.Abs(path); err != nil {
		panic(err)
	} else if out, err = filepath.EvalSymlinks(abs); err != nil {
		panic(err)
	}
	return
}

func ln_sf(target, path string) (created bool, err error) {
	current, e := os.Readlink(path)
	if e != nil || current != target {
		if err = os.RemoveAll(path); err != nil {
			return
		}
		if err = os.MkdirAll(filepath.Dir(path), 0777); err != nil {
			return
		}
		if err = os.Symlink(target, path); err != nil {
			return
		}
		created = true
	}
	return
}

func yaml_copy(in interface{}, out interface{}) {
	if bts, err := yaml.Marshal(in); err != nil {
		panic(err)
	} else if err = yaml.Unmarshal(bts, out); err != nil {
		panic(err)
	}
}

type RequestedDep struct {
	name        string
	Git_url     string
	Import_path string
	Ref         string
	Subpath     string
	Source      []string // TODO: hmmm...
}

// TODO: factor Ref out of here into separate thing
type ResolvedDep struct {
	name      string
	Git_url   string
	Commit_id string
	Subpath   string
	Source    []string
}

// A Begotten or Begotten.lock file contains exactly one of these in YAML format.
type BegottenFileStruct struct {
	// in Begotten:
	Deps         map[string]interface{} // either string or RequestedDep
	Repo_aliases map[string]interface{} // either string or subset of RequestedDep {git_url, ref}

	// in Begotten.lock:
	Meta struct {
		File_version int
		Generated_by string
	}
	Repo_deps     map[string][]string
	Resolved_deps map[string]ResolvedDep
}

type BegottenFile struct {
	data BegottenFileStruct
}

func BegottenFileNew(fn string) (bf *BegottenFile) {
	bf = new(BegottenFile)
	bf.data.Meta.File_version = -1
	if data, err := ioutil.ReadFile(fn); err != nil {
		panic(err)
	} else if err := yaml.Unmarshal(data, &bf.data); err != nil {
		panic(err)
	}
	ver := bf.data.Meta.File_version
	if ver != -1 && ver != FILE_VERSION {
		panic(fmt.Errorf("Incompatible file version for %r; please run 'begot update'.", ver))
	}
	return
}

type SortedStringMap yaml.MapSlice

func (sm SortedStringMap) Len() int {
	return len(sm)
}
func (sm SortedStringMap) Less(i, j int) bool {
	return sm[i].Key.(string) < sm[j].Key.(string)
}
func (sm SortedStringMap) Swap(i, j int) {
	sm[i], sm[j] = sm[j], sm[i]
}

func (bf *BegottenFile) save(fn string, deps []ResolvedDep, repo_deps map[string][]string) {
	// We have to sort everything so the output is deterministic. go-yaml
	// doesn't write maps in sorted order, so we have to convert them to
	// yaml.MapSlices and sort those.
	var out struct {
		Meta struct {
			File_version int
			Generated_by string
		}
		Repo_deps     SortedStringMap
		Resolved_deps SortedStringMap
	}

	out.Meta.File_version = FILE_VERSION
	out.Meta.Generated_by = CODE_VERSION

	for k, v := range repo_deps {
		sort.StringSlice(v).Sort()
		out.Repo_deps = append(out.Repo_deps, yaml.MapItem{k, v})
	}
	sort.Sort(out.Repo_deps)

	for _, dep := range deps {
		out.Resolved_deps = append(out.Resolved_deps, yaml.MapItem{dep.name, dep})
	}
	sort.Sort(out.Resolved_deps)

	if data, err := yaml.Marshal(out); err != nil {
		panic(err)
	} else if err := ioutil.WriteFile(fn, data, 0666); err != nil {
		panic(err)
	}
}

func (bf *BegottenFile) default_git_url_from_repo_path(repo_path string) string {
	// Hook for testing:
	test_repo_path := os.Getenv("BEGOT_TEST_REPOS")
	if strings.HasPrefix(repo_path, "begot.test/") && test_repo_path != "" {
		return "file://" + filepath.Join(test_repo_path, repo_path)
	}
	// Default to https for other repos:
	return "https://" + repo_path
}

func (bf *BegottenFile) parse_dep(name string, v interface{}, default_branch, default_source string) (dep RequestedDep) {
	dep.name = name

	if _, ok := v.(string); ok {
		v = map[interface{}]interface{}{"import_path": v}
	}

	mv, ok := v.(map[interface{}]interface{})
	if !ok {
		panic(fmt.Errorf("Dependency value must be string or dict, got %T: %v", v, v))
	}

	yaml_copy(mv, &dep)

	if dep.Import_path != "" {
		parts := strings.Split(dep.Import_path, "/")
		if repo_parts, ok := KNOWN_GIT_SERVERS[parts[0]]; !ok {
			panic(fmt.Errorf("Unknown git server %r for %r", parts[0], name))
		} else {
			repo_path := strings.Join(parts[:repo_parts+1], "/")
			dep.Git_url = bf.default_git_url_from_repo_path(repo_path)
			dep.Subpath = strings.Join(parts[repo_parts+1:], "/")

			// Redirect through repo aliases:
			if alias, ok := bf.data.Repo_aliases[repo_path]; ok {
				var aliasdep RequestedDep // only allow git_url and ref
				if aliasstr, ok := alias.(string); ok {
					aliasstr = bf.default_git_url_from_repo_path(aliasstr)
					alias = yaml.MapSlice{yaml.MapItem{"git_url", aliasstr}}
				}
				yaml_copy(alias, &aliasdep)
				if aliasdep.Git_url != "" {
					dep.Git_url = aliasdep.Git_url
				}
				if aliasdep.Ref != "" {
					dep.Ref = aliasdep.Ref
				}
			}
		}
	}

	if dep.Git_url == "" {
		panic(fmt.Errorf("Missing 'git_url' for %q; only git is supported for now", name))
	}

	if dep.Ref == "" {
		dep.Ref = default_branch
	}

	if len(dep.Source) == 0 {
		dep.Source = []string{default_source}
	}

	return
}

func (bf *BegottenFile) requested_deps() (out []RequestedDep) {
	out = make([]RequestedDep, len(bf.data.Deps))
	i := 0
	for name, v := range bf.data.Deps {
		out[i] = bf.parse_dep(name, v, DEFAULT_BRANCH, "explicit")
		i++
	}
	return
}

func (bf *BegottenFile) resolved_deps() (out []ResolvedDep) {
	out = make([]ResolvedDep, len(bf.data.Resolved_deps))
	i := 0
	for name, v := range bf.data.Resolved_deps {
		v.name = name
		out[i] = v
		i++
	}
	return
}

func (bf *BegottenFile) repo_deps() map[string][]string {
	if bf.data.Repo_deps == nil {
		bf.data.Repo_deps = make(map[string][]string)
	}
	return bf.data.Repo_deps
}

type Env struct {
	Home             string
	BegotCache       string
	DepWorkspaceDir  string
	CodeWorkspaceDir string
	RepoDir          string
	CacheLock        string
}

func EnvNew() (env *Env) {
	env = new(Env)
	env.Home = os.Getenv("HOME")
	env.BegotCache = os.Getenv("BEGOT_CACHE")
	if env.BegotCache == "" {
		env.BegotCache = filepath.Join(env.Home, ".cache", "begot")
	}
	env.DepWorkspaceDir = filepath.Join(env.BegotCache, "depwk")
	env.CodeWorkspaceDir = filepath.Join(env.BegotCache, "wk")
	env.RepoDir = filepath.Join(env.BegotCache, "repo")
	env.CacheLock = filepath.Join(env.BegotCache, "lock")
	return
}

type Builder struct {
	env *Env

	code_root string
	code_wk   string
	dep_wk    string

	bf *BegottenFile

	requested_deps []RequestedDep
	resolved_deps  []ResolvedDep

	repo_deps_lock sync.Mutex
	repo_deps      map[string][]string

	locked_refs map[string]string

	cached_lf_hash string
}

func BuilderNew(env *Env, code_root string, use_lockfile bool) (b *Builder) {
	b = new(Builder)
	b.env = env

	b.code_root = realpath(code_root)
	hsh := sha1str(b.code_root)[:8]
	b.code_wk = filepath.Join(env.CodeWorkspaceDir, hsh)
	b.dep_wk = filepath.Join(env.DepWorkspaceDir, hsh)

	var fn string
	if use_lockfile {
		fn = filepath.Join(b.code_root, BEGOTTEN_LOCK)
	} else {
		fn = filepath.Join(b.code_root, BEGOTTEN)
	}
	b.bf = BegottenFileNew(fn)
	b.repo_deps = make(map[string][]string)

	return
}

func (b *Builder) _all_repos(deps []ResolvedDep) (out map[string]string) {
	out = make(map[string]string)
	for _, dep := range deps {
		out[dep.Git_url] = dep.Commit_id
	}
	return
}

func (b *Builder) get_locked_refs_for_update(limits []string) (out map[string]string) {
	out = make(map[string]string)
	if len(limits) == 0 {
		return
	}

	defer func() {
		if err := recover(); err != nil {
			panic(fmt.Errorf("You must have a %s to do a limited update.", BEGOTTEN_LOCK))
		}
	}()
	bf_lock := BegottenFileNew(filepath.Join(b.code_root, BEGOTTEN_LOCK))

	lock_deps := bf_lock.resolved_deps()
	lock_repo_deps := bf_lock.repo_deps()

	match := func(name string) bool {
		for _, limit := range limits {
			if matched, err := filepath.Match(limit, name); err != nil {
				panic(err)
			} else if matched {
				return true
			}
		}
		return false
	}

	repos_to_update := make(map[string]bool)
	for _, dep := range lock_deps {
		if match(dep.name) {
			repos_to_update[dep.Git_url] = true
		}
	}

	// transitive closure
	n := -1
	for len(repos_to_update) != n {
		n = len(repos_to_update)
		repos := make([]string, 0, len(repos_to_update))
		for repo, _ := range repos_to_update {
			repos = append(repos, repo)
		}
		for _, repo := range repos {
			if deps, ok := lock_repo_deps[repo]; ok {
				for _, dep := range deps {
					repos_to_update[dep] = true
				}
			}
		}
	}

	for _, dep := range lock_deps {
		if !repos_to_update[dep.Git_url] {
			out[dep.Git_url] = dep.Commit_id
		}
	}
	return
}

// Each call to _process is a goroutine and has exclusive responsibility for one repo.
func (b *Builder) _process(
	url string,
	should_fetch bool,
	my_chan chan RequestedDep,
	new_dep func(RequestedDep),
	postpone_dep func(RequestedDep),
	out_dep func(ResolvedDep),
	in_wg, out_wg *sync.WaitGroup) {

	defer func() {
		if err := recover(); err != nil {
			fmt.Printf("Error: %s\n", err)
			os.Exit(1)
		}
	}()

	// problem 1: we need a ref before we can setup and get deps of this repo.
	// DONE.
	// problem 2: the rewrite step needs to be able to look up a name from a
	// url+path. we can hash so that they all end up at the same name, but that
	// doesn't help to match up sub-deps to explicit deps, and we need to do
	// that to avoid duplicating. DONE.
	// problem 3: we need to postpone processing when we get a FLOAT.
	// might be solved?
	// problem 4: if we get all floats, we need to default to master and _then_
	// process more deps. that strongly suggests a round structure...

	out := make(map[string]ResolvedDep) // map from subpath to ResolvedDep

	locked, was_locked := b.locked_refs[url]
	var have string

	for dep := range my_chan {
		var want string
		if was_locked {
			want = locked
		} else {
			want = b._resolve_ref(url, dep.Ref, should_fetch)
			should_fetch = false // only fetch at most once
		}

		if have != "" {
			if want != FLOAT {
				if have != want {
					panic(fmt.Errorf("Conflicting versions for %s: have %s, want %s (%s)",
						url, have, want, dep.Ref))
				}
			}
		} else {
			if want != FLOAT {
				have = want
				b._setup_repo(url, have, new_dep)
			} else {
				postpone_dep(dep)
				in_wg.Done()
				continue
			}
		}

		if outdep, ok := out[dep.Subpath]; ok {
			for _, new_src := range dep.Source {
				if !contains_str(outdep.Source, new_src) {
					outdep.Source = append(outdep.Source, new_src)
				}
			}
			out[dep.Subpath] = outdep
		} else {
			out[dep.Subpath] = ResolvedDep{
				name:      dep.name,
				Git_url:   url,
				Commit_id: have,
				Subpath:   dep.Subpath,
				Source:    dep.Source,
			}
		}

		in_wg.Done()
	}

	for _, dep := range out {
		out_dep(dep)
	}
	out_wg.Done()
}

func (b *Builder) setup_repos(fetch bool, limits []string) *Builder {
	b.locked_refs = b.get_locked_refs_for_update(limits)
	b.requested_deps = b.bf.requested_deps()
	// After this point, b.locked_refs and b.requested_deps are constant, so
	// other goroutines can read from them.

	input := make(chan RequestedDep, 500) // FIXME: should use unlimited buffer

	var out_wg, in_wg sync.WaitGroup

	postponed_deps := make([]RequestedDep, 0)
	var output_lock, postponed_lock sync.Mutex

	new_dep := func(dep RequestedDep) {
		in_wg.Add(1)
		input <- dep
	}
	postpone_dep := func(dep RequestedDep) {
		postponed_lock.Lock()
		postponed_deps = append(postponed_deps, dep)
		postponed_lock.Unlock()
	}
	out_dep := func(dep ResolvedDep) {
		output_lock.Lock()
		b.resolved_deps = append(b.resolved_deps, dep)
		output_lock.Unlock()
	}

	go func() {
		chans := make(map[string]chan RequestedDep)
		for dep := range input {
			if c, ok := chans[dep.Git_url]; ok {
				c <- dep
			} else {
				c = make(chan RequestedDep)
				chans[dep.Git_url] = c
				out_wg.Add(1)
				go b._process(dep.Git_url, fetch, c, new_dep, postpone_dep, out_dep, &in_wg, &out_wg)
				c <- dep
			}
		}
		for _, c := range chans {
			close(c)
		}
	}()

	for _, dep := range b.requested_deps {
		new_dep(dep)
	}

	prev_round := -1
	for {
		// Wait for all the deps to make their way through _process.
		in_wg.Wait()

		// Examine postponed deps.
		postponed_lock.Lock()

		if len(postponed_deps) == 0 {
			// We're done.
			break
		} else if len(postponed_deps) == prev_round {
			// No progress. Default everything so far to master.
			// FIXME: is this really an accurate signal of no progress?
			for i := range postponed_deps {
				postponed_deps[i].Ref = DEFAULT_BRANCH
			}
		}

		// Send them back again.
		prev_round = len(postponed_deps)
		for _, dep := range postponed_deps {
			new_dep(dep)
		}
		postponed_deps = postponed_deps[0:0]

		postponed_lock.Unlock()
	}

	// This close gets propagated to all of the _process routines and causes
	// them to dump their output.
	close(input)
	// Wait for everyone to output their deps
	out_wg.Wait()

	return b
}

func (b *Builder) save_lockfile() *Builder {
	b.repo_deps_lock.Lock()
	defer b.repo_deps_lock.Unlock()
	b.bf.save(filepath.Join(b.code_root, BEGOTTEN_LOCK), b.resolved_deps, b.repo_deps)
	return b
}

func (b *Builder) _record_repo_dep(src_url, dep_url string) {
	b.repo_deps_lock.Lock()
	defer b.repo_deps_lock.Unlock()

	if src_url != dep_url {
		lst := b.repo_deps[src_url]
		if !contains_str(lst, dep_url) {
			b.repo_deps[src_url] = append(lst, dep_url)
		}
	}
}

func (b *Builder) _repo_dir(url string) string {
	return filepath.Join(b.env.RepoDir, sha1str(url))
}

var RE_SHA1_HASH = regexp.MustCompile("[[:xdigit:]]{40}")

func (b *Builder) _resolve_ref(url, ref string, should_fetch bool) (resolved_ref string) {
	if ref == FLOAT {
		return FLOAT
	}

	repo_dir := b._repo_dir(url)

	if fi, err := os.Stat(repo_dir); err != nil || !fi.Mode().IsDir() {
		fmt.Printf("Cloning %s\n", url)
		cc("/", "git", "clone", "-q", url, repo_dir)
		// Get into detached head state so we can manipulate things without
		// worrying about messing up a branch.
		cc(repo_dir, "git", "checkout", "-q", "--detach")
	} else if should_fetch {
		fmt.Printf("Updating %s\n", url)
		cc(repo_dir, "git", "fetch", "-q")
	}

	if RE_SHA1_HASH.MatchString(ref) {
		return ref
	}

	for _, pfx := range []string{"origin/", ""} {
		cmd := Command(repo_dir, "git", "rev-parse", "--verify", pfx+ref)
		cmd.Stderr = nil
		if outb, err := cmd.Output(); err == nil {
			resolved_ref = strings.TrimSpace(string(outb))
			return
		}
	}
	panic(fmt.Errorf("Can't resolve reference %q for %s", ref, url))
}

func (b *Builder) _setup_repo(url, resolved_ref string, new_dep func(dep RequestedDep)) {
	repo_dir := b._repo_dir(url)

	fmt.Printf("Fixing imports in %s\n", url)
	cmd := Command(repo_dir, "git", "reset", "-q", "--hard", resolved_ref)
	if err := cmd.Run(); err != nil {
		fmt.Printf("Updating %s\n", url)
		cc(repo_dir, "git", "fetch", "-q")
		cc(repo_dir, "git", "reset", "-q", "--hard", resolved_ref)
	}

	// Match up sub-deps to our deps.
	sub_dep_map := make(map[string]string)
	self_deps := []RequestedDep{}
	sub_bg_path := filepath.Join(repo_dir, BEGOTTEN_LOCK)
	if _, err := os.Stat(sub_bg_path); err == nil {
		sub_bg := BegottenFileNew(sub_bg_path)
		// Add implicit and explicit external dependencies.
		for _, sub_dep := range sub_bg.resolved_deps() {
			for i, s := range sub_dep.Source {
				sub_dep.Source[i] = url + " => " + s
			}

			b._record_repo_dep(url, sub_dep.Git_url)

			new_name := implicit_name(sub_dep.Git_url, sub_dep.Subpath)
			our_dep := b._lookup_explicit_dep(sub_dep.Git_url, sub_dep.Subpath)
			if our_dep != nil {
				// Even though we have a dep already, we send another copy
				// through to check that the versions match.
				new_name = our_dep.name
			}
			sub_dep_map[sub_dep.name] = new_name
			new_dep(RequestedDep{
				name:    new_name,
				Git_url: sub_dep.Git_url,
				Ref:     sub_dep.Commit_id,
				Subpath: sub_dep.Subpath,
				Source:  sub_dep.Source,
			})
		}
		// Allow relative import paths within this repo.
		e := filepath.Walk(repo_dir, func(path string, fi os.FileInfo, err error) error {
			basename := filepath.Base(path)
			if err != nil {
				return err
			} else if fi.IsDir() && basename[0] == '.' {
				return filepath.SkipDir
			} else if !fi.IsDir() || path == repo_dir {
				return nil
			}
			relpath := path[len(repo_dir)+1:]
			our_dep := b._lookup_explicit_dep(url, relpath)
			if our_dep != nil {
				sub_dep_map[relpath] = our_dep.name
			} else {
				dep := RequestedDep{
					name:    implicit_name(url, relpath),
					Git_url: url,
					Subpath: relpath,
					Ref:     resolved_ref,
					Source:  []string{fmt.Sprintf("self dep for %s in %s", relpath, url)},
				}
				sub_dep_map[relpath] = dep.name
				self_deps = append(self_deps, dep)
			}
			return nil
		})
		if e != nil {
			panic(e)
		}
	}

	used_rewrites := make(map[string]bool)
	b._rewrite_imports(url, repo_dir, &sub_dep_map, &used_rewrites, new_dep)
	msg := fmt.Sprintf("rewritten by begot for %s", b.code_root)
	cc(repo_dir, "git", "commit", "--allow-empty", "-a", "-q", "-m", msg)

	// Add only the self-deps that were used, to reduce clutter.
	for _, self_dep := range self_deps {
		if used_rewrites[self_dep.name] {
			new_dep(self_dep)
		}
	}
}

func (b *Builder) _rewrite_imports(src_url, repo_dir string, sub_dep_map *map[string]string, used_rewrites *map[string]bool, new_dep func(RequestedDep)) {
	filepath.Walk(repo_dir, func(path string, fi os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if strings.HasSuffix(path, ".go") {
			b._rewrite_file(src_url, path, sub_dep_map, used_rewrites, new_dep)
		}
		return nil
	})
	return
}

func (b *Builder) _rewrite_file(src_url, path string, sub_dep_map *map[string]string, used_rewrites *map[string]bool, new_dep func(RequestedDep)) {
	bts, err := ioutil.ReadFile(path)
	if err != nil {
		panic(err)
	}

	fs := token.NewFileSet()
	f, err := parser.ParseFile(fs, path, bts, parser.ImportsOnly)
	if err != nil {
		panic(err)
	}

	var pos int
	var out bytes.Buffer
	out.Grow(len(bts) * 5 / 4)

	for _, imp := range f.Imports {
		start := fs.Position(imp.Path.Pos()).Offset
		end := fs.Position(imp.Path.End()).Offset
		orig_import := string(bts[start+1 : end-1])
		rewritten := b._rewrite_import(src_url, orig_import, sub_dep_map, used_rewrites, new_dep)
		if orig_import != rewritten {
			out.Write(bts[pos : start+1])
			out.WriteString(rewritten)
			pos = end - 1
		}
	}
	out.Write(bts[pos:])

	if err := ioutil.WriteFile(path, out.Bytes(), 0666); err != nil {
		panic(err)
	}
}

func (b *Builder) _rewrite_import(src_url, imp string, sub_dep_map *map[string]string, used_rewrites *map[string]bool, new_dep func(RequestedDep)) (new_imp string) {
	new_imp = imp
	if rewrite, ok := (*sub_dep_map)[imp]; ok {
		new_imp = rewrite
		(*used_rewrites)[rewrite] = true
	} else {
		parts := strings.Split(imp, "/")
		if _, ok := KNOWN_GIT_SERVERS[parts[0]]; ok {
			new_imp = b._lookup_dep_name(src_url, imp, new_dep)
		}
	}
	return
}

func (b *Builder) _lookup_dep_name(src_url, imp string, new_dep func(RequestedDep)) (name string) {
	as_dep := b.bf.parse_dep("", imp, FLOAT, src_url)
	as_dep.name = implicit_name(as_dep.Git_url, as_dep.Subpath)
	b._record_repo_dep(src_url, as_dep.Git_url)

	// Check if this matches one of our explicit deps.
	our_dep := b._lookup_explicit_dep(as_dep.Git_url, as_dep.Subpath)
	if our_dep != nil {
		return our_dep.name
	} else { // Otherwise it's a new implicit dep.
		new_dep(as_dep)
		return as_dep.name
	}
}

func (b *Builder) _lookup_explicit_dep(git_url string, subpath string) *RequestedDep {
	for _, dep := range b.requested_deps {
		if dep.Git_url == git_url && dep.Subpath == subpath {
			return &dep
		}
	}
	return nil
}

func (b *Builder) tag_repos() {
	// Run this after setup_repos.
	var wg sync.WaitGroup
	for url, ref := range b._all_repos(b.resolved_deps) {
		wg.Add(1)
		go func(url, ref string) {
			repo_dir := b._repo_dir(url)

			out := co(repo_dir, "git", "tag", "--force", b._tag_hash(ref))
			for _, line := range strings.SplitAfter(out, "\n") {
				if !strings.HasPrefix(line, "Updated tag ") {
					fmt.Print(line)
				}
			}
			wg.Done()
		}(url, ref)
	}
	wg.Wait()
}

func (b *Builder) _tag_hash(ref string) string {
	// We want to tag the current state with a name that depends on:
	// 1. The base ref that we rewrote from.
	// 2. The full set of deps that describe how we rewrote imports.
	// The contents of Begotten.lock suffice for (2):

	if b.cached_lf_hash == "" {
		lockfile := filepath.Join(b.code_root, BEGOTTEN_LOCK)
		if bts, err := ioutil.ReadFile(lockfile); err != nil {
			panic(err)
		} else {
			b.cached_lf_hash = sha1bts(bts)
		}
	}
	return "_begot_rewrote_" + sha1str(ref+b.cached_lf_hash)
}

func (b *Builder) run(args []string) {
	deps := b.bf.resolved_deps()
	b._reset_to_tags(deps)

	// Set up code_wk.
	cbin := filepath.Join(b.code_wk, "bin")
	depsrc := filepath.Join(b.dep_wk, "src")
	empty_dep := filepath.Join(depsrc, EMPTY_DEP)
	os.MkdirAll(cbin, 0777)
	os.MkdirAll(empty_dep, 0777)
	if _, err := ln_sf(cbin, filepath.Join(b.code_root, "bin")); err != nil {
		panic(fmt.Errorf("It looks like you have an existing 'bin' directory. " +
			"Please remove it before using begot."))
	}
	ln_sf(b.code_root, filepath.Join(b.code_wk, "src"))

	old_links := make(map[string]bool)
	filepath.Walk(depsrc, func(path string, fi os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if fi.Mode()&os.ModeType == os.ModeSymlink {
			old_links[path] = true
		}
		return nil
	})

	for _, dep := range deps {
		path := filepath.Join(depsrc, dep.name)
		target := filepath.Join(b._repo_dir(dep.Git_url), dep.Subpath)
		if created, err := ln_sf(target, path); err != nil {
			panic(err)
		} else if created {
			// If we've created or changed this symlink, any pkg files that go may
			// have compiled from it should be invalidated.
			// Note: This makes some assumptions about go's build layout. It should
			// be safe enough, though it may be simpler to just blow away everything
			// if any dep symlinks change.
			pkgs, _ := filepath.Glob(filepath.Join(b.dep_wk, "pkg", "*", dep.name+".*"))
			for _, pkg := range pkgs {
				os.RemoveAll(pkg)
			}
		}
		delete(old_links, path)
	}

	// Remove unexpected links.
	for old_link := range old_links {
		os.RemoveAll(old_link)
	}

	// Try to remove all directories; ignore ENOTEMPTY errors.
	var dirs []string
	filepath.Walk(depsrc, func(path string, fi os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if fi.IsDir() {
			dirs = append(dirs, path)
		}
		return nil
	})
	for i := len(dirs) - 1; i >= 0; i-- {
		if err := syscall.Rmdir(dirs[i]); err != nil && err != syscall.ENOTEMPTY {
			panic(err)
		}
	}

	// Set up empty dep.
	//
	// The go tool tries to be helpful by not rebuilding modified code if that
	// code is in a workspace and no packages from that workspace are mentioned
	// on the command line. See cmd/go/pkg.go:isStale around line 680.
	//
	// We are explicitly managing all of the workspaces in our GOPATH and do
	// indeed want to rebuild everything when dependencies change. That is
	// required by the goal of reproducible builds: the alternative would mean
	// what you get for this build depends on the state of a previous build.
	//
	// The go tool doesn't provide any way of disabling this "helpful"
	// functionality. The simplest workaround is to always mention a package from
	// the dependency workspace on the command line. Hence, we add an empty
	// package.
	empty_go := filepath.Join(empty_dep, "empty.go")
	if fi, err := os.Stat(empty_go); err != nil || !fi.Mode().IsRegular() {
		os.MkdirAll(filepath.Dir(empty_go), 0777)
		if err := ioutil.WriteFile(empty_go, []byte(fmt.Sprintf("package %s\n", EMPTY_DEP)), 0666); err != nil {
			panic(err)
		}
	}

	// Overwrite any existing GOPATH.
	if argv0, err := exec.LookPath(args[0]); err != nil {
		panic(err)
	} else {
		os.Setenv("GOPATH", fmt.Sprintf("%s:%s", b.code_wk, b.dep_wk))
		os.Chdir(b.code_root)
		err := syscall.Exec(argv0, args, os.Environ())
		panic(fmt.Errorf("exec failed: %s", err))
	}
}

func (b *Builder) _reset_to_tags(deps []ResolvedDep) {
	var wg sync.WaitGroup
	for url, ref := range b._all_repos(deps) {
		wg.Add(1)
		go func(url, ref string) {
			defer func() {
				if recover() != nil {
					fmt.Fprintf(os.Stderr, "Begotten.lock refers to a missing local commit. "+
						"Please run 'begot fetch' first.")
					os.Exit(1)
				}
			}()

			repo_dir := b._repo_dir(url)

			if fi, err := os.Stat(repo_dir); err != nil || !fi.Mode().IsDir() {
				panic("not directory")
			}
			cc(repo_dir, "git", "reset", "-q", "--hard", "tags/"+b._tag_hash(ref))
			wg.Done()
		}(url, ref)
	}
	wg.Wait()
}

func (b *Builder) clean() {
	os.RemoveAll(b.dep_wk)
	os.RemoveAll(b.code_wk)
	os.Remove(filepath.Join(b.code_root, "bin"))
}

func get_gopath(env *Env) string {
	// This duplicates logic in Builder, but we want to just get the GOPATH without
	// parsing anything.
	for {
		if _, err := os.Stat(BEGOTTEN); err == nil {
			break
		}
		if wd, err := os.Getwd(); err != nil {
			panic(err)
		} else if wd == "/" {
			panic(fmt.Errorf("Couldn't find %s file", BEGOTTEN))
		}
		if err := os.Chdir(".."); err != nil {
			panic(err)
		}
	}
	hsh := sha1str(realpath("."))[:8]
	code_wk := filepath.Join(env.CodeWorkspaceDir, hsh)
	dep_wk := filepath.Join(env.DepWorkspaceDir, hsh)
	return code_wk + ":" + dep_wk
}

var _cache_lock *os.File

func lock_cache(env *Env) {
	os.MkdirAll(env.BegotCache, 0777)
	_cache_lock, err := os.OpenFile(env.CacheLock, os.O_CREATE|os.O_RDWR, 0666)
	if err != nil {
		panic(err)
	}
	err = syscall.Flock(int(_cache_lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if err != nil {
		panic(fmt.Errorf("Can't lock %r", env.BegotCache))
	}
	// Leave file open for lifetime of this process and anything exec'd by this
	// process.
}

func print_help(ret int) {
	fmt.Fprintln(os.Stderr, "FIXME")
	os.Exit(ret)
}

func main() {
	env := EnvNew()

	defer func() {
		if err := recover(); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %s\n", err)
			os.Exit(1)
		}
	}()

	lock_cache(env)

	if len(os.Args) < 2 {
		print_help(1)
	}

	switch os.Args[1] {
	case "update":
		BuilderNew(env, ".", false).setup_repos(true, os.Args[2:]).save_lockfile().tag_repos()
	case "just_rewrite":
		BuilderNew(env, ".", false).setup_repos(false, []string{}).save_lockfile().tag_repos()
	case "fetch":
		BuilderNew(env, ".", true).setup_repos(false, []string{}).tag_repos()
	case "build":
		BuilderNew(env, ".", true).run([]string{"go", "install", "./...", EMPTY_DEP})
	case "go":
		BuilderNew(env, ".", true).run(append([]string{"go"}, os.Args[2:]...))
	case "exec":
		BuilderNew(env, ".", true).run(os.Args[2:])
	case "clean":
		BuilderNew(env, ".", false).clean()
	case "gopath":
		fmt.Println(get_gopath(env))
	case "help":
		print_help(0)
	default:
		fmt.Fprintf(os.Stderr, "Unknown subcommand %q\n", os.Args[1])
		print_help(1)
	}
}

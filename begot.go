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
	FILE_VERSION = 1
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

type Dep struct {
	name        string
	Aliases     []string
	Git_url     string
	Import_path string `yaml:",omitempty"`
	Ref         string
	Subpath     string
	Source      []string
}

// A Begotten or Begotten.lock file contains exactly one of these in YAML format.
type BegottenFileStruct struct {
	Deps map[string]interface{} // either string or Dep
	Meta struct {
		File_version int
		Generated_by string
	}
	Repo_aliases map[string]interface{} // either string or subset of Dep {git_url, ref}
	Repo_deps    map[string][]string
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

func (bf *BegottenFile) save(fn string) {
	// We have to sort everything so the output is deterministic. go-yaml
	// doesn't write maps in sorted order, so we have to convert them to
	// yaml.MapSlices and sort those.
	var out struct {
		Deps SortedStringMap
		Meta struct {
			File_version int
			Generated_by string
		}
		Repo_aliases SortedStringMap
		Repo_deps    SortedStringMap
	}

	out.Meta.File_version = FILE_VERSION
	out.Meta.Generated_by = CODE_VERSION

	for k, v := range bf.data.Deps {
		dep := v.(Dep)
		dep.Import_path = ""
		sort.StringSlice(dep.Aliases).Sort()
		out.Deps = append(out.Deps, yaml.MapItem{k, dep})
	}
	sort.Sort(out.Deps)

	for k, v := range bf.data.Repo_aliases {
		out.Repo_aliases = append(out.Repo_aliases, yaml.MapItem{k, v})
	}
	sort.Sort(out.Repo_aliases)

	for k, v := range bf.data.Repo_deps {
		sort.StringSlice(v).Sort()
		out.Repo_deps = append(out.Repo_deps, yaml.MapItem{k, v})
	}
	sort.Sort(out.Repo_deps)

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

func (bf *BegottenFile) parse_dep(name string, v interface{}, default_branch string) (dep Dep) {
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
			dep.Aliases = append(dep.Aliases, dep.Import_path)

			// Redirect through repo aliases:
			if alias, ok := bf.data.Repo_aliases[repo_path]; ok {
				var aliasdep Dep // only allow git_url and ref
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

	return
}

func (bf *BegottenFile) deps() (out []Dep) {
	out = make([]Dep, len(bf.data.Deps))
	i := 0
	for name, v := range bf.data.Deps {
		out[i] = bf.parse_dep(name, v, DEFAULT_BRANCH)
		i++
	}
	return
}

func (bf *BegottenFile) set_deps(deps []Dep) {
	bf.data.Deps = make(map[string]interface{})
	for _, dep := range deps {
		bf.data.Deps[dep.name] = dep
	}
}

func (bf *BegottenFile) repo_deps() map[string][]string {
	if bf.data.Repo_deps == nil {
		bf.data.Repo_deps = make(map[string][]string)
	}
	return bf.data.Repo_deps
}

func (bf *BegottenFile) set_repo_deps(repo_deps map[string][]string) {
	bf.data.Repo_deps = repo_deps
}

func (dep *Dep) set_implicit_name() {
	dep.name = "_begot_" + sha1str(dep.Git_url+"/"+dep.Subpath)
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

	bf   *BegottenFile
	deps []Dep

	repo_deps_lock sync.Mutex
	repo_deps      map[string][]string

	repo_locks_lock sync.Mutex
	repo_locks      map[string]*sync.Mutex

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
	b.deps = b.bf.deps()
	if !use_lockfile {
		for i := range b.deps {
			b.deps[i].Source = []string{"explicit"}
		}
	}
	b.repo_deps = b.bf.repo_deps()

	b.repo_locks = make(map[string]*sync.Mutex)

	return
}

func (b *Builder) _all_repos() (out map[string]string) {
	out = make(map[string]string)
	for _, dep := range b.deps {
		out[dep.Git_url] = dep.Ref
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

	lock_deps := bf_lock.deps()
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
			out[dep.Git_url] = dep.Ref
		}
	}
	return
}

func (b *Builder) setup_repos(fetch bool, limits []string) *Builder {
	var repo_versions_lock, new_deps_lock, to_process_lock sync.Mutex
	repo_versions := make(map[string]string)
	var new_deps, to_process []*Dep

	var should_fetch func(string) bool
	if fetch {
		var fetched_set_lock sync.Mutex
		fetched_set := make(map[string]bool)
		should_fetch = func(url string) bool {
			fetched_set_lock.Lock()
			defer fetched_set_lock.Unlock()
			if fetched_set[url] {
				return false
			} else {
				fetched_set[url] = true
				return true
			}
		}
	}

	locked_refs := b.get_locked_refs_for_update(limits)

	var wg sync.WaitGroup

	var process_dep func(*Dep)
	process_dep = func(dep *Dep) {
		defer func() {
			if err := recover(); err != nil {
				fmt.Printf("Error: %s\n", err)
				os.Exit(1)
			}
		}()

		want := locked_refs[dep.Git_url]
		if want == "" {
			want = b._resolve_ref(dep.Git_url, dep.Ref, should_fetch)
		}

		repo_versions_lock.Lock()
		have := repo_versions[dep.Git_url]
		if have != "" {
			repo_versions_lock.Unlock()
			if want != FLOAT {
				if have != want {
					panic(fmt.Errorf("Conflicting versions for %s: have %s, want %s (%s)",
						dep.Git_url, have, want, dep.Ref))
				}
			} else {
				want = have
			}
		} else {
			if want != FLOAT {
				repo_versions[dep.Git_url] = want
				repo_versions_lock.Unlock()

				repo_deps := b._setup_repo(dep.Git_url, want)
				for i := range repo_deps {
					wg.Add(1)
					go process_dep(&repo_deps[i])
				}
			} else {
				repo_versions_lock.Unlock()
				to_process_lock.Lock()
				to_process = append(to_process, dep)
				to_process_lock.Unlock()
				wg.Done()
				return
			}
		}
		dep.Ref = want

		new_deps_lock.Lock()
		new_deps = append(new_deps, dep)
		new_deps_lock.Unlock()
		wg.Done()
	}

	// Throw in all the deps from the file to get started.
	to_process = make([]*Dep, len(b.deps))
	for i := range b.deps {
		to_process[i] = &b.deps[i]
	}

	// Process one round at a time.
	last_round := -1
	for {
		to_process_lock.Lock()
		if len(to_process) == 0 {
			break
		} else if len(to_process) == last_round {
			// No progress, everything left must be floating. Set to default.
			for _, dep := range to_process {
				fmt.Printf("Assuming %q for implicit dep of %s on %s\n",
					DEFAULT_BRANCH, dep.name, dep.Git_url)
				dep.Ref = DEFAULT_BRANCH
			}
		}
		for _, dep := range to_process {
			wg.Add(1)
			go process_dep(dep)
		}
		last_round = len(to_process)
		to_process = nil
		to_process_lock.Unlock()

		wg.Wait()
	}

	b.deps = make([]Dep, len(new_deps))
	for i := range new_deps {
		b.deps[i] = *new_deps[i]
	}

	return b
}

func (b *Builder) save_lockfile() *Builder {
	b.repo_deps_lock.Lock()
	defer b.repo_deps_lock.Unlock()

	// Should only be called when loaded from Begotten, not lockfile.
	b.bf.set_deps(b.deps)
	b.bf.set_repo_deps(b.repo_deps)
	b.bf.save(filepath.Join(b.code_root, BEGOTTEN_LOCK))
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

func (b *Builder) _repo_lock(repo_dir string) (lock *sync.Mutex) {
	b.repo_locks_lock.Lock()
	defer b.repo_locks_lock.Unlock()
	if lock = b.repo_locks[repo_dir]; lock == nil {
		lock = new(sync.Mutex)
		b.repo_locks[repo_dir] = lock
	}
	return lock
}

func (b *Builder) _repo_dir(url string) string {
	return filepath.Join(b.env.RepoDir, sha1str(url))
}

var RE_SHA1_HASH = regexp.MustCompile("[[:xdigit:]]{40}")

func (b *Builder) _resolve_ref(url, ref string, should_fetch func(string) bool) (resolved_ref string) {
	if ref == FLOAT {
		return FLOAT
	}

	repo_dir := b._repo_dir(url)

	repo_lock := b._repo_lock(repo_dir)
	repo_lock.Lock()
	defer repo_lock.Unlock()

	if fi, err := os.Stat(repo_dir); err != nil || !fi.Mode().IsDir() {
		fmt.Printf("Cloning %s\n", url)
		cc("/", "git", "clone", "-q", url, repo_dir)
		// Get into detached head state so we can manipulate things without
		// worrying about messing up a branch.
		cc(repo_dir, "git", "checkout", "-q", "--detach")
	} else if should_fetch != nil && should_fetch(url) {
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

func (b *Builder) _setup_repo(url, resolved_ref string) (new_deps []Dep) {
	repo_dir := b._repo_dir(url)

	repo_lock := b._repo_lock(repo_dir)
	repo_lock.Lock()
	defer repo_lock.Unlock()

	fmt.Printf("Fixing imports in %s\n", url)
	cmd := Command(repo_dir, "git", "reset", "-q", "--hard", resolved_ref)
	if err := cmd.Run(); err != nil {
		fmt.Printf("Updating %s\n", url)
		cc(repo_dir, "git", "fetch", "-q")
		cc(repo_dir, "git", "reset", "-q", "--hard", resolved_ref)
	}

	// Match up sub-deps to our deps.
	sub_dep_map := make(map[string]string)
	self_deps := []Dep{}
	sub_bg_path := filepath.Join(repo_dir, BEGOTTEN_LOCK)
	if _, err := os.Stat(sub_bg_path); err == nil {
		sub_bg := BegottenFileNew(sub_bg_path)
		// Add implicit and explicit external dependencies.
		for _, sub_dep := range sub_bg.deps() {
			for i, s := range sub_dep.Source {
				sub_dep.Source[i] = url + " => " + s
			}

			b._record_repo_dep(url, sub_dep.Git_url)

			our_dep := b._lookup_dep_by_git_url_and_path(sub_dep.Git_url, sub_dep.Subpath)

			if our_dep != nil {
				if sub_dep.Ref != our_dep.Ref {
					real_ref := b._resolve_ref(our_dep.Git_url, our_dep.Ref, nil)
					panic(fmt.Errorf("Conflict: %s depends on %s at %s, we depend on it at %s (%s)",
						url, sub_dep.Git_url, sub_dep.Ref, our_dep.Ref, real_ref))
				}
				sub_dep_map[sub_dep.name] = our_dep.name
			} else {
				orig_name := sub_dep.name
				sub_dep.set_implicit_name()
				//sub_dep.Source = append(sub_dep.Source, fmt.Sprintf("transitive dep of %s in %s", orig_name, url))
				sub_dep_map[orig_name] = sub_dep.name
				new_deps = append(new_deps, sub_dep)
			}
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
			our_dep := b._lookup_dep_by_git_url_and_path(url, relpath)
			if our_dep != nil {
				sub_dep_map[relpath] = our_dep.name
			} else {
				dep := Dep{name: "", Git_url: url, Subpath: relpath, Ref: resolved_ref,
					Source: []string{fmt.Sprintf("self dep for %s in %s", relpath, url)}}
				dep.set_implicit_name()
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
	deps := b._rewrite_imports(url, repo_dir, &sub_dep_map, &used_rewrites)
	new_deps = append(new_deps, deps...)
	msg := fmt.Sprintf("rewritten by begot for %s", b.code_root)
	cc(repo_dir, "git", "commit", "--allow-empty", "-a", "-q", "-m", msg)

	// Add only the self-deps that were used, to reduce clutter.
	for _, self_dep := range self_deps {
		if used_rewrites[self_dep.name] {
			new_deps = append(new_deps, self_dep)
		}
	}

	return
}

func (b *Builder) _rewrite_imports(src_url, repo_dir string, sub_dep_map *map[string]string, used_rewrites *map[string]bool) (new_deps []Dep) {
	filepath.Walk(repo_dir, func(path string, fi os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if strings.HasSuffix(path, ".go") {
			deps := b._rewrite_file(src_url, path, sub_dep_map, used_rewrites)
			new_deps = append(new_deps, deps...)
		}
		return nil
	})
	return
}

func (b *Builder) _rewrite_file(src_url, path string, sub_dep_map *map[string]string, used_rewrites *map[string]bool) (new_deps []Dep) {
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
		rewritten, deps := b._rewrite_import(src_url, orig_import, sub_dep_map, used_rewrites)
		new_deps = append(new_deps, deps...)
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
	return
}

func (b *Builder) _rewrite_import(src_url, imp string, sub_dep_map *map[string]string, used_rewrites *map[string]bool) (new_imp string, new_deps []Dep) {
	new_imp = imp
	if rewrite, ok := (*sub_dep_map)[imp]; ok {
		new_imp = rewrite
		(*used_rewrites)[rewrite] = true
	} else {
		parts := strings.Split(imp, "/")
		if _, ok := KNOWN_GIT_SERVERS[parts[0]]; ok {
			new_imp, new_deps = b._lookup_dep_name(src_url, imp)
		}
	}
	return
}

func (b *Builder) _lookup_dep_name(src_url, imp string) (name string, new_deps []Dep) {
	// Check if this matches one of our explicit deps.
	// TODO: It's kind of gross to look through b.deps here. But b.deps is
	// read-only while we're processing deps, so it's ok.
	for _, dep := range b.deps {
		if contains_str(dep.Aliases, imp) {
			name = dep.name
			b._record_repo_dep(src_url, dep.Git_url)
			return
		}
	}

	// Otherwise it's a new implicit dep.
	dep := b.bf.parse_dep("", imp, FLOAT)
	dep.set_implicit_name()
	dep.Source = []string{fmt.Sprintf("%s -> %s", src_url, imp)}
	name = dep.name
	new_deps = []Dep{dep}
	b._record_repo_dep(src_url, dep.Git_url)
	return
}

func (b *Builder) _lookup_dep_by_git_url_and_path(git_url string, subpath string) *Dep {
	// TODO: same comment as above
	for _, dep := range b.deps {
		if dep.Git_url == git_url && dep.Subpath == subpath {
			return &dep
		}
	}
	return nil
}

func (b *Builder) tag_repos() {
	// Run this after setup_repos.
	var wg sync.WaitGroup
	for url, ref := range b._all_repos() {
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
	b._reset_to_tags()

	// Set up code_wk.
	cbin := filepath.Join(b.code_wk, "bin")
	depsrc := filepath.Join(b.dep_wk, "src")
	empty_dep := filepath.Join(depsrc, EMPTY_DEP)
	os.MkdirAll(filepath.Join(cbin, empty_dep), 0777)
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

	for _, dep := range b.deps {
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

func (b *Builder) _reset_to_tags() {
	var wg sync.WaitGroup
	for url, ref := range b._all_repos() {
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

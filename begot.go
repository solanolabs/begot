// Copyright (c) 2014-2015 Solano Labs Inc.  All Rights Reserved.

package main

import (
	"os"
	"path/filepath"
	//import sys, os, fcntl, re, subprocess, hashlib, errno, shutil, fnmatch, glob
	//import yaml

	"gopkg.in/yaml.v2"
)

const (
	BEGOTTEN      = "Begotten"
	BEGOTTEN_LOCK = "Begotten.lock"

	EMPTY_DEP = "_begot_empty_dep"

	// This is an identifier for the version of begot. It gets written into
	// Begotten.lock.
	//CODE_VERSION = 'begot-1.0-' + hashlib.sha1(open(__file__).read()).hexdigest()[:8]
	CODE_VERSION = "FIXME"
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

type BegottenFileError error
type DependencyError error

func check_call(args ...string) {
}

func check_output(args ...string) (out string) {
}

func ln_sf(target, path string) (created bool) {
	current, err := os.Readlink(path)
	if err != nil || current != target {
		os.RemoveAll(path)
		os.MkdirAll(filepath.Dirname(path))
		os.Symlink(target, path)
		created = true
	}
	return
}

type Dep struct {
}

//yaml.add_representer(Dep, yaml.representer.Representer.represent_dict)

type BegottenFile struct {
}

func BegottenFileNew(fn string) (bf *BegottenFile) {
	//bf.raw = yaml.safe_load(open(fn))
	//file_version = bf.raw.get('meta', {}).get('file_version')
	//if file_version is not None and file_version != FILE_VERSION:
	//  raise BegottenFileError(
	//      "Incompatible file version for %r; please run 'begot update'." % fn)
}

func (bf *BegottenFile) save(fn) {
	//bf.raw.setdefault('meta', {}).update({
	//  'file_version': FILE_VERSION,
	//  'generated_by': CODE_VERSION,
	//})
	//yaml.dump(bf.raw, open(fn, 'w'), default_flow_style=False)
}

func (bf *BegottenFile) default_git_url_from_repo_path(repo_path) {
	//# Hook for testing:
	//if repo_path.startswith('begot.test/') and os.Getenv('BEGOT_TEST_REPOS'):
	//  return 'file://' + filepath.Join(os.Getenv('BEGOT_TEST_REPOS'), repo_path)
	//# Default to https for other repos:
	//return 'https://' + repo_path
}

func (bf *BegottenFile) get_repo_alias(repo_path) {
	//return bf.raw.get('repo_aliases', {}).get(repo_path)
}

func (bf *BegottenFile) parse_dep(name, val) {
	//if isinstance(val, str):
	//  val = {'import_path': val}
	//if not isinstance(val, dict):
	//  raise BegottenFileError("Dependency value must be string or dict")
	//
	//val = dict(val)
	//
	//val.setdefault('aliases', [])
	//
	//if 'import_path' in val:
	//  parts = val['import_path'].split('/')
	//  repo_parts = KNOWN_GIT_SERVERS.get(parts[0])
	//  if repo_parts is None:
	//    raise BegottenFileError("Unknown git server %r for %r" % (
	//      parts[0], name))
	//  repo_path = '/'.filepath.Join(parts[:repo_parts+1])
	//  val['git_url'] = bf.default_git_url_from_repo_path(repo_path)
	//  val['subpath'] = '/'.filepath.Join(parts[repo_parts+1:])
	//  val['aliases'].append(val['import_path'])
	//
	//  # Redirect through repo aliases:
	//  alias = bf.get_repo_alias(repo_path)
	//  if alias is not None:
	//    if isinstance(alias, str):
	//      alias = {'git_url': bf.default_git_url_from_repo_path(alias)}
	//    for attr in 'git_url', 'ref':
	//      if attr in alias:
	//        val[attr] = alias[attr]
	//
	//if 'git_url' not in val:
	//  raise BegottenFileError(
	//      "Missing 'git_url' for %r; only git is supported for now" % name)
	//
	//if 'subpath' not in val:
	//  val['subpath'] = ''
	//
	//if 'ref' not in val:
	//  val['ref'] = 'master'
	//
	//return Dep(name=name, git_url=val['git_url'], subpath=val['subpath'],
	//    ref=val['ref'], aliases=val['aliases'])
}

func (bf *BegottenFile) deps() {
	//if 'deps' not in bf.raw:
	//  raise BegottenFileError("Missing 'deps' section")
	//deps = bf.raw['deps']
	//if not isinstance(deps, dict):
	//  raise BegottenFileError("'deps' is not a dict")
	//return [bf.parse_dep(name, val) for name, val in deps.iteritems()]
}

func (bf *BegottenFile) set_deps(deps) {
	//def without_name(dep):
	//  dep = dict(dep)
	//  dep.pop('name')
	//  return dep
	//bf.raw['deps'] = dict((dep.name, without_name(dep)) for dep in deps)
}

func (bf *BegottenFile) repo_deps() {
	//return bf.raw.get('repo_deps', {})
}

func (bf *BegottenFile) set_repo_deps(repo_deps) {
	//bf.raw['repo_deps'] = repo_deps
}

type Builder struct {
	HOME               string
	BEGOT_CACHE        string
	DEP_WORKSPACE_DIR  string
	CODE_WORKSPACE_DIR string
	REPO_DIR           string
	CACHE_LOCK         string
}

func BuilderNew(code_root string, use_lockfile bool) (b *Builder) {
	b = new(Builder)
	b.HOME = os.Getenv("HOME")
	b.BEGOT_CACHE = os.Getenv("BEGOT_CACHE") || filepath.Join(HOME, ".cache", "begot")
	b.DEP_WORKSPACE_DIR = filepath.Join(BEGOT_CACHE, "depwk")
	b.CODE_WORKSPACE_DIR = filepath.Join(BEGOT_CACHE, "wk")
	b.REPO_DIR = filepath.Join(BEGOT_CACHE, "repo")
	b.CACHE_LOCK = filepath.Join(BEGOT_CACHE, "lock")

	//b.code_root = os.path.realpath(code_root)
	//hsh = hashlib.sha1(b.code_root).hexdigest()[:8]
	//b.code_wk = filepath.Join(CODE_WORKSPACE_DIR, hsh)
	//b.dep_wk = filepath.Join(DEP_WORKSPACE_DIR, hsh)
	//if use_lockfile:
	//  fn = filepath.Join(b.code_root, BEGOTTEN_LOCK)
	//else:
	//  fn = filepath.Join(b.code_root, BEGOTTEN)
	//try:
	//  b.bg = Begotten(fn)
	//except BegottenFileError, e:
	//  print >>sys.stderr, e
	//  sys.exit(1)
	//b.deps = b.bg.deps()
	//b.repo_deps = b.bg.repo_deps()
}

func (b *Builder) _all_repos() {
	//return dict((dep.git_url, dep.ref) for dep in b.deps)
}

func (b *Builder) get_locked_refs_for_update(limits) {
	//if not limits: return {}
	//try:
	//  bg_lock = Begotten(filepath.Join(b.code_root, BEGOTTEN_LOCK))
	//except IOError:
	//  print >>sys.stderr, "You must have a %s to do a limited update." % BEGOTTEN_LOCK
	//  sys.exit(1)
	//except BegottenFileError, e:
	//  print >>sys.stderr, e
	//  sys.exit(1)
	//deps = bg_lock.deps()
	//repo_deps = bg_lock.repo_deps()
	//match = lambda name: any(fnmatch.fnmatch(name, limit) for limit in limits)
	//repos_to_update = set(dep.git_url for dep in deps if match(dep.name))
	//n = None
	//while len(repos_to_update) != n:
	//  n = len(repos_to_update)
	//  for repo in list(repos_to_update):
	//    repos_to_update.update(repo_deps.get(repo, []))
	//return dict((dep.git_url, dep.ref) for dep in deps
	//            if dep.git_url not in repos_to_update)
}

func (b *Builder) setup_repos(fetch, limits /*=None*/) {
	//processed_deps = 0
	//repo_versions = {}
	//if fetch:
	//  fetched_set = set()
	//else:
	//  fetched_set = None
	//
	//locked_refs = b.get_locked_refs_for_update(limits)
	//
	//while processed_deps < len(b.deps):
	//  repos_to_setup = []
	//
	//  for dep in b.deps[processed_deps:]:
	//    have = repo_versions.get(dep.git_url)
	//
	//    if fetch and dep.name.startswith('_begot_implicit/') and have is not None:
	//      # Implicit deps take the revision of an explicit dep from the same
	//      # repo, if one exists.
	//      dep.ref = have
	//      continue
	//
	//    want = locked_refs.get(dep.git_url)
	//    if want is None:
	//      want = b._resolve_ref(dep.git_url, dep.ref, fetched_set)
	//
	//    if have is not None:
	//      if have != want:
	//        raise DependencyError(
	//            "Conflicting versions for %r: have %s, want %s (%s)" % (
	//            dep.name, have, want, dep.ref))
	//    else:
	//      repo_versions[dep.git_url] = want
	//      repos_to_setup.append(dep.git_url)
	//    dep.ref = want
	//
	//  processed_deps = len(b.deps)
	//
	//  # This will add newly-found dependencies to b.deps.
	//  for url in repos_to_setup:
	//    b._setup_repo(url, repo_versions[url])
	//
	//return self
}

func (b *Builder) save_lockfile() {
	//# Should only be called when loaded from Begotten, not lockfile.
	//b.bg.set_deps(b.deps)
	//b.bg.set_repo_deps(b.repo_deps)
	//b.bg.save(filepath.Join(b.code_root, BEGOTTEN_LOCK))
	//return self
}

func (b *Builder) _add_implicit_dep(name, val) {
	//dep = b.bg.parse_dep(name, val)
	//b.deps.append(dep)
	//return dep
}

func (b *Builder) _record_repo_dep(git_url) {
	//if b.processing_repo != git_url:
	//  lst = b.repo_deps.setdefault(b.processing_repo, [])
	//  if git_url not in lst:
	//    lst.append(git_url)
}

func (b *Builder) _repo_dir(url) {
	//url_hash = hashlib.sha1(url).hexdigest()
	//return filepath.Join(REPO_DIR, url_hash)
}

func (b *Builder) _resolve_ref(url, ref, fetched_set) {
	//repo_dir = b._repo_dir(url)
	//if not os.path.isdir(repo_dir):
	//  print "Cloning %s" % url
	//  cc(['git', 'clone', '-q', url, repo_dir], cwd='/')
	//  # Get into detached head state so we can manipulate things without
	//  # worrying about messing up a branch.
	//  cc(['git', 'checkout', '-q', '--detach'], cwd=repo_dir)
	//elif fetched_set is not None:
	//  if url not in fetched_set:
	//    print "Updating %s" % url
	//    cc(['git', 'fetch'], cwd=repo_dir)
	//    fetched_set.add(url)
	//
	//try:
	//  return co(['git', 'rev-parse', '--verify', 'origin/' + ref],
	//      cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()
	//except subprocess.CalledProcessError:
	//  return co(['git', 'rev-parse', '--verify', ref],
	//      cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()
}

func (b *Builder) _setup_repo(url, resolved_ref) {
	//b.processing_repo = url
	//hsh = hashlib.sha1(url).hexdigest()[:8]
	//repo_dir = b._repo_dir(url)
	//
	//print "Fixing imports in %s" % url
	//try:
	//  cc(['git', 'reset', '-q', '--hard', resolved_ref], cwd=repo_dir)
	//except subprocess.CalledProcessError:
	//  print "Missing local ref %r, updating" % resolved_ref
	//  cc(['git', 'fetch', '-q'], cwd=repo_dir)
	//  cc(['git', 'reset', '-q', '--hard', resolved_ref], cwd=repo_dir)
	//
	//# Match up sub-deps to our deps.
	//sub_dep_map = {}
	//self_deps = []
	//sub_bg_path = filepath.Join(repo_dir, BEGOTTEN_LOCK)
	//if os.path.exists(sub_bg_path):
	//  sub_bg = Begotten(sub_bg_path)
	//  # Add implicit and explicit external dependencies.
	//  for sub_dep in sub_bg.deps():
	//    b._record_repo_dep(sub_dep.git_url)
	//    our_dep = b._lookup_dep_by_git_url_and_path(
	//        sub_dep.git_url, sub_dep.subpath)
	//    if our_dep is not None:
	//      if sub_dep.ref != our_dep.ref:
	//        raise DependencyError(
	//            "Conflict: %s depends on %s at %s, we depend on it at %s" % (
	//            url, sub_dep.git_url, sub_dep.ref, our_dep.ref))
	//      sub_dep_map[sub_dep.name] = our_dep.name
	//    else:
	//      # Include a hash of this repo identifier so that if two repos use the
	//      # same dep name to refer to two different things, they don't conflict
	//      # when we flatten deps.
	//      transitive_name = '_begot_transitive_%s/%s' % (hsh, sub_dep.name)
	//      sub_dep_map[sub_dep.name] = transitive_name
	//      sub_dep.name = transitive_name
	//      b.deps.append(sub_dep)
	//  # Allow relative import paths within this repo.
	//  for dirpath, dirnames, files in os.walk(repo_dir):
	//    dirnames[:] = filter(lambda n: n[0] != '.', dirnames)
	//    for dn in dirnames:
	//      relpath = filepath.Join(dirpath, dn)[len(repo_dir)+1:]
	//      our_dep = b._lookup_dep_by_git_url_and_path(url, relpath)
	//      if our_dep is not None:
	//        sub_dep_map[relpath] = our_dep.name
	//      else:
	//        # See comment on _lookup_dep_name for re.sub rationale.
	//        self_name = '_begot_self_%s/%s' % (hsh, re.sub(r'\W', '_', relpath))
	//        sub_dep_map[relpath] = self_name
	//        self_deps.append(Dep(name=self_name,
	//          git_url=url, subpath=relpath, ref=resolved_ref, aliases=[]))
	//
	//used_rewrites = {}
	//b._rewrite_imports(repo_dir, sub_dep_map, used_rewrites)
	//msg = 'rewritten by begot for %s' % b.code_root
	//cc(['git', 'commit', '--allow-empty', '-a', '-q', '-m', msg], cwd=repo_dir)
	//
	//# Add only the self-deps that were used, to reduce clutter.
	//vals = set(used_rewrites.values())
	//b.deps.extend(dep for dep in self_deps if dep.name in vals)
}

func (b *Builder) _rewrite_imports(repo_dir, sub_dep_map, used_rewrites) {
	//for dirpath, dirnames, files in os.walk(repo_dir):
	//  dirnames[:] = filter(lambda n: n[0] != '.', dirnames)
	//  for fn in files:
	//    if fn.endswith('.go'):
	//      b._rewrite_file(filepath.Join(dirpath, fn), sub_dep_map, used_rewrites)
}

func (b *Builder) _rewrite_file(path, sub_dep_map, used_rewrites) {
	//# TODO: Ew ew ew.. do this using the go parser.
	//code = open(path).read().splitlines(True)
	//inimports = False
	//for i, line in enumerate(code):
	//  rewrite = inimports
	//  if inimports and ')' in line:
	//      inimports = False
	//  elif line.startswith('import ('):
	//    inimports = True
	//  elif line.startswith('import '):
	//    rewrite = True
	//  if rewrite:
	//    code[i] = b._rewrite_line(line, sub_dep_map, used_rewrites)
	//open(path, 'w').write(''.filepath.Join(code))
}

func (b *Builder) _rewrite_line(line, sub_dep_map, used_rewrites) {
	//def repl(m):
	//  imp = m.group(1)
	//  if imp in sub_dep_map:
	//    imp = used_rewrites[imp] = sub_dep_map[imp]
	//  else:
	//    parts = imp.split('/')
	//    if parts[0] in KNOWN_GIT_SERVERS:
	//      imp = b._lookup_dep_name(imp)
	//  return '"%s"' % imp
	//return re.sub(r'"([^"]+)"', repl, line)
}

func (b *Builder) _lookup_dep_name(imp) {
	//for dep in b.deps:
	//  if imp in dep.aliases:
	//    b._record_repo_dep(dep.git_url)
	//    return dep.name
	//
	//# Each dep turns into a symlink at build time. Packages can be nested, so we
	//# might depend on 'a' and 'a/b'. If we create a symlink for 'a', we can't
	//# also create 'a/b'. So rename it to 'a_b'.
	//name = '_begot_implicit/' + re.sub(r'\W', '_', imp)
	//dep = b._add_implicit_dep(name, imp)
	//b._record_repo_dep(dep.git_url)
	//return name
}

func (b *Builder) _lookup_dep_by_git_url_and_path(git_url, subpath) {
	//for dep in b.deps:
	//  if dep.git_url == git_url and dep.subpath == subpath:
	//    return dep
}

func (b *Builder) tag_repos() {
	//# Run this after setup_repos.
	//for url, ref in b._all_repos().iteritems():
	//  out = co(['git', 'tag', '--force', b._tag_hash(ref)], cwd=b._repo_dir(url))
	//  for line in out.splitlines():
	//    if not line.startswith('Updated tag '): print line
}

func (b *Builder) _tag_hash(ref, cached_lf_hash /*=[]*/) {
	//# We want to tag the current state with a name that depends on:
	//# 1. The base ref that we rewrote from.
	//# 2. The full set of deps that describe how we rewrote imports.
	//# The contents of Begotten.lock suffice for (2):
	//if not cached_lf_hash:
	//  lockfile = filepath.Join(b.code_root, BEGOTTEN_LOCK)
	//  cached_lf_hash.append(hashlib.sha1(file(lockfile).read()).hexdigest())
	//lf_hash = cached_lf_hash[0]
	//return '_begot_rewrote_' + hashlib.sha1(ref + lf_hash).hexdigest()
}

func (b *Builder) run(args ...string) {
	//try:
	//  b._reset_to_tags()
	//except subprocess.CalledProcessError:
	//  print >>sys.stderr, ("Begotten.lock refers to a missing local commit. "
	//      "Please run 'begot fetch' first.")
	//  sys.exit(1)
	//
	//# Set up code_wk.
	//cbin = filepath.Join(b.code_wk, 'bin')
	//depsrc = filepath.Join(b.dep_wk, 'src')
	//empty_dep = filepath.Join(depsrc, EMPTY_DEP)
	//os.MkdirAll(cbin, empty_dep)
	//try:
	//  _ln_sf(cbin, filepath.Join(b.code_root, 'bin'))
	//except OSError:
	//  print >>sys.stderr, "It looks like you have an existing 'bin' directory."
	//  print >>sys.stderr, "Please remove it before using begot."
	//  sys.exit(1)
	//_ln_sf(b.code_root, filepath.Join(b.code_wk, 'src'))
	//
	//old_deps = set(co(['find', depsrc, '-type', 'l', '-print0']).split('\0'))
	//old_deps.discard('')
	//
	//for dep in b.deps:
	//  path = filepath.Join(b.dep_wk, 'src', dep.name)
	//  target = filepath.Join(b._repo_dir(dep.git_url), dep.subpath)
	//  if _ln_sf(target, path):
	//    # If we've created or changed this symlink, any pkg files that go may
	//    # have compiled from it should be invalidated.
	//    # Note: This makes some assumptions about go's build layout. It should
	//    # be safe enough, though it may be simpler to just blow away everything
	//    # if any dep symlinks change.
	//    os.RemoveAll(*glob.glob(filepath.Join(b.dep_wk, 'pkg', '*', dep.name + '.*')))
	//  old_deps.discard(path)
	//
	//# Remove unexpected deps.
	//if old_deps:
	//  for old_dep in old_deps:
	//    os.remove(old_dep)
	//  for dir in co(['find', depsrc, '-depth', '-type', 'd', '-print0']).split('\0'):
	//    if not dir: continue
	//    try:
	//      os.rmdir(dir)
	//    except OSError, e:
	//      if e.errno != errno.ENOTEMPTY:
	//        raise
	//
	//# Set up empty dep.
	//#
	//# The go tool tries to be helpful by not rebuilding modified code if that
	//# code is in a workspace and no packages from that workspace are mentioned
	//# on the command line. See cmd/go/pkg.go:isStale around line 680.
	//#
	//# We are explicitly managing all of the workspaces in our GOPATH and do
	//# indeed want to rebuild everything when dependencies change. That is
	//# required by the goal of reproducible builds: the alternative would mean
	//# what you get for this build depends on the state of a previous build.
	//#
	//# The go tool doesn't provide any way of disabling this "helpful"
	//# functionality. The simplest workaround is to always mention a package from
	//# the dependency workspace on the command line. Hence, we add an empty
	//# package.
	//empty_go = filepath.Join(empty_dep, 'empty.go')
	//if not os.path.isfile(empty_go):
	//  open(empty_go, 'w').write('package %s\n' % EMPTY_DEP)
	//
	//# Overwrite any existing GOPATH.
	//os.putenv('GOPATH', ':'.filepath.Join((b.code_wk, b.dep_wk)))
	//os.chdir(b.code_root)
	//os.execvp(args[0], args)
}

func (b *Builder) _reset_to_tags() {
	//for url, ref in b._all_repos().iteritems():
	//  wd = b._repo_dir(url)
	//  if not os.path.isdir(wd):
	//    print >>sys.stderr, ("Begotten.lock refers to a missing local commit. "
	//        "Please run 'begot fetch' first.")
	//    sys.exit(1)
	//  cc(['git', 'reset', '-q', '--hard', 'tags/' + b._tag_hash(ref)], cwd=wd)
}

func (b *Builder) clean() {
	//os.RemoveAll(b.dep_wk)
	//os.RemoveAll(b.code_wk)
	//os.Remove(filepath.Join(b.code_root, 'bin'))
}

func get_gopath(code_root /*='.'*/) {
	//# This duplicates logic in Builder, but we want to just get the GOPATH without
	//# parsing anything.
	//while not os.path.exists(BEGOTTEN):
	//  if os.getcwd() == '/':
	//    return None
	//  os.chdir('..')
	//hsh = hashlib.sha1(os.path.realpath('.')).hexdigest()[:8]
	//code_wk = filepath.Join(CODE_WORKSPACE_DIR, hsh)
	//dep_wk = filepath.Join(DEP_WORKSPACE_DIR, hsh)
	//return ':'.filepath.Join((code_wk, dep_wk))
}

func lock_cache() {
	//try:
	//  global _cache_lock
	//  os.MkdirAll(BEGOT_CACHE)
	//  _cache_lock = file(CACHE_LOCK, 'w')
	//  fcntl.flock(_cache_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
	//  # Leave file open for lifetime of this process and anything exec'd by this
	//  # process.
	//except IOError:
	//  print >>sys.stderr, "Can't lock %r" % BEGOT_CACHE
	//  sys.exit(1)
}

func print_help(ret /*=1*/) {
	//print __doc__.split('---\n')[-1],
	//sys.exit(ret)
}

func main() {
	yaml.Unmarshal([]byte{}, &struct{}{})

	//lock_cache()
	//
	//try:
	//  cmd = argv[0]
	//except IndexError:
	//  print_help()
	//
	//if cmd == 'update':
	//  Builder(use_lockfile=False).setup_repos(fetch=True, limits=argv[1:]).save_lockfile().tag_repos()
	//elif cmd == 'just_rewrite':
	//  Builder(use_lockfile=False).setup_repos(fetch=False).save_lockfile().tag_repos()
	//elif cmd == 'fetch':
	//  Builder(use_lockfile=True).setup_repos(fetch=False).tag_repos()
	//elif cmd == 'build':
	//  Builder(use_lockfile=True).run('go', 'install', './...', EMPTY_DEP)
	//elif cmd == 'go':
	//  Builder(use_lockfile=True).run('go', *argv[1:])
	//elif cmd == 'exec':
	//  Builder(use_lockfile=True).run(*argv[1:])
	//elif cmd == 'clean':
	//  Builder(use_lockfile=False).clean()
	//elif cmd == 'gopath':
	//  gopath = get_gopath()
	//  if gopath is None:
	//    sys.exit(1)
	//  print gopath
	//elif cmd == 'help':
	//  print_help(0)
	//else:
	//  print >>sys.stderr, "Unknown subcommand %r" % cmd
	//  print_help()
}

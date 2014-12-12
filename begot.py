#!/usr/bin/env python2

r"""

Begot is a different approach to managing Go dependencies.

There are lots of desirable features in the Go dependency design space:

  - reproducible builds
  - source-based distribution
  - no reliance on central repository
  - self-contained builds (no reliance on any third party)
  - versioned import paths
  - dependent code should not be rewritten
  - works with workspaces within git repos
  - works with git repos within workspaces
  - works with git repos not within workspaces
  - works with private repos
  - compatibility with go build/install
  - able to use go-gettable dependencies
  - produces go-gettable dependencies
  - no extraneous metadata file
  - relocatable repos without rewriting imports
  - manages dependent scm repos for you

It is impossible to satisfy all of these at once. That's why there are so many
existing options in this space. Furthermore, people place different priorities
on these features and prefer different subsets along the satisfiable frontier.
That's why people can't agree on one option.

Begot is a point in the space that works for us. It may not work for everyone.

---

The Go creators tried to eliminate the need for dependency metadata by encoding
all the needed metadata into the import path. Unfortunately, they decided to
encode just enough metadata to be dangerous (i.e. one place where the code could
be fetched from), but not enough to be complete. The import path lacks:

  - any sort of version identifier
  - a content hash to ensure reproducibility
  - a protocol to be used for fetching (for private repos)
  - alternative locations to fetch the code from if the canonical source is
    unavailable
  - directions to use a custom fork rather than the canonical source

Most Go depdency tools try to preserve some of the existing properties of import
paths, which leads to a confusing model and other problems (TODO: elaborate
here). We'd rather throw them out completely. When using begot, you use
user-chosen import paths that name the package but don't contain any information
about where to obtain the actual code. That's in an external metadata file.
Additionally, relative imports within the repo use import paths relative to the
repo root (as if the repo was directly within "src" in a go workspace), instead
of including a canonical path to the repo with every import. Thus, we
immediately see the following advantages and disadvantages:

  Pros:
  - builds are completely reproducible
  - supporting private repos is trivial
  - you can switch to a custom fork of a dependency with a metadata change
  - no danger of multiple copies of a dependency (as long as no one in the
    dependency tree vendors things with paths rewritten to be within their repo)
  - repos are trivially relocatable without rewriting imports
  - you can use relative dependencies without setting up an explicit workspace

  Cons:
  - repos are not go-gettable
  - a wrapper around the go tool is required

Begot also adds some amount of transparent scm repo management, since we do need
to rewrite import paths, and if we're rewriting code, we should use an scm
system to track those changes.

---

Currently, the fear that a particular dependency or version of a dependency will
become unavailable and a build no longer reproducible leads to the practice of
vendoring dependencies within a project repo. Instead of combining multiple
logical repos into one (and discarding history and metadata), our approach is to
combine begot with another tool that manages mirrors of third-party dependencies
in scm hosting that you control, e.g. forks within your own github organization.
(This other tool doesn't exist yet.)

---

Usage:

Somewhere within your repo, put some .go files or packages in a directory with a
file named Begotten. That code will end up within a 'src' directory in a
temporary workspace created by begot, along with your dependencies.

A Begotten file is in yaml format and looks roughly like this:

  deps:
    third_party/systemstat: bitbucket.org/bertimus9/systemstat
    third_party/gorilla/mux: github.com/gorilla/mux
    third_party/docker:
      import_path: github.com/fsouza/go-dockerclient
      ref: 0.2.1
    third_party/goamz/s3: github.com/mitchellh/goamz/s3
    tddium/util: github.com/solanolabs/tddium_go/util
    tddium/client:
      git_url: git@github.com:solanolabs/tddium_go
      subpath: client
  repo_aliases:
    github.com/solanolabs/tddium_go:
      git_url: git@github.com:solanolabs/tddium_go
      #ref: some_branch
    github.com/mitchellh/goamz: github.com/wkj/goamz

Notes:
- A plain string is shorthand for {"import_path": ...}
- You can override the git url used, in a single place, which will apply to the
  whole project and all of its dependencies.
- You can refer to a branch, tag, or commit hash, using the 'ref' option (which
  defaults to 'master').
- You can redirect all packages in a whole repo to another repo, and optionally
  pin it to a given ref.
- Using ssh-style git urls allows using private repos easily.

In your code, you can then refer to these deps with the import path
"third_party/docker", "third_party/gorilla/mux", etc. and begot will set up the
temporary workspace correctly.

Subcommands:

  begot update:
    1. Reads Begotten
    2. Fetches (and updates) transitive dependencies
    3. (Re-)resolves references
    4. Rewrites imports in dependencies
    5. writes locked references to Begotten.lock

    Use this when:
    - You've just written a new Begotten file.
    - You want to bump the version of all dependencies (when you've requested
      'master' or another branch).

  begot just_rewrite:
    Does what 'begot update' does except does not fetch new code if the
    dependency is already present in the cache.

    In general, you shouldn't need to use this. Prefer 'begot update' or 'begot
    fetch', as appropriate. This is useful if something has changed about the
    way begot rewrites dependencies and you want to fix it without bumping
    versions.

  begot fetch:
    1. Reads Begotten.lock
    2. Fetches transitive dependencies
    3. Rewrites imports in dependencies

    Use this when:
    - You've just cloned or updated your code repo and you want to get the
      dependencies required for building.

  begot build/go/exec:
    1. Reads Begotten.lock
    2. Ensures the dependency repos are at the correct revisions and have
       correctly-rewritten imports
    3. Sets up a symlink from 'bin' in the current directory to 'bin' in the
       first go workspace in GOPATH, i.e., the place where 'go install' will put
       binaries.
    4. Runs the given command in a go workspace with the dependencies specified
       in Begotten.lock. 'begot go' is a shorthand for 'begot exec go', and
       'begot build' is a shorthand for 'begot go install ./...'. In short:
         begot build         runs   go install ./...   [*]
         begot go <args>     runs   go <args>
         begot exec <args>   runs   <args>

    Use this when:
    - You want to build your project.

    [*]: This is actually slightly more complicated. See comments in Builder.run

  begot clean:
    1. Removes the temprary workspaces, including built binaries.

  begot gopath:
    1. Prints the GOPATH that would be used for 'begot build' (except skipping
       most of the work).

    Use this from shell or editor hooks.

    Here's some sample vim script:

      function! SetBegotGoPath()
        let gopath = substitute(system("begot gopath"), "\n", "", "")
        if v:shell_error == 0
          let $GOPATH = gopath
        endif
      endfunction
      call SetBegotGoPath()

  begot help:
    1. Prints this text.

"""

import sys, os, fcntl, re, subprocess, hashlib, errno, shutil, fnmatch, yaml

BEGOTTEN = 'Begotten'
BEGOTTEN_LOCK = 'Begotten.lock'
EMPTY_DEP = '_begot_empty_dep'

# This is an identifier for the version of begot. It gets written into
# Begotten.lock.
CODE_VERSION = 'begot-1.0-' + hashlib.sha1(open(__file__).read()).hexdigest()[:8]

# This should change if the format of Begotten.lock changes in an incompatible
# way. (But prefer changing it in compatible ways and not incrementing this.)
FILE_VERSION = 1

# Known public servers and how many path components form the repo name.
KNOWN_GIT_SERVERS = {
  'github.com': 2,
  'bitbucket.org': 2,
}

cc = subprocess.check_call
co = subprocess.check_output
join = os.path.join
HOME = os.getenv('HOME')
BEGOT_CACHE = os.getenv('BEGOT_CACHE') or join(HOME, '.cache', 'begot')
DEP_WORKSPACE_DIR = join(BEGOT_CACHE, 'depwk')
CODE_WORKSPACE_DIR = join(BEGOT_CACHE, 'wk')
REPO_DIR = join(BEGOT_CACHE, 'repo')
CACHE_LOCK = join(BEGOT_CACHE, 'lock')


class BegottenFileError(Exception): pass
class DependencyError(Exception): pass

def _mkdir_p(*dirs):
  for d in dirs:
    if not os.path.isdir(d):
      os.makedirs(d)
def _rm(*paths):
  for p in paths:
    try: os.remove(p)
    except OSError: pass
def _ln_sf(target, path):
  if not os.path.islink(path) or os.readlink(path) != target:
    _rm(path)
    _mkdir_p(os.path.dirname(path))
    os.symlink(target, path)


class Dep(dict):
  def __getattr__(self, k):
    return self[k]
  def __setattr__(self, k, v):
    self[k] = v
yaml.add_representer(Dep, yaml.representer.Representer.represent_dict)


class Begotten(object):
  def __init__(self, fn):
    self.raw = yaml.safe_load(open(fn))
    file_version = self.raw.get('meta', {}).get('file_version')
    if file_version is not None and file_version != FILE_VERSION:
      raise BegottenFileError(
          "Incompatible file version for %r; please run 'begot update'." % fn)

  def save(self, fn):
    self.raw.setdefault('meta', {}).update({
      'file_version': FILE_VERSION,
      'generated_by': CODE_VERSION,
    })
    yaml.dump(self.raw, open(fn, 'w'), default_flow_style=False)

  def default_git_url_from_repo_path(self, repo_path):
    return 'https://' + repo_path

  def get_repo_alias(self, repo_path):
    return self.raw.get('repo_aliases', {}).get(repo_path)

  def parse_dep(self, name, val):
    if isinstance(val, str):
      val = {'import_path': val}
    if not isinstance(val, dict):
      raise BegottenFileError("Dependency value must be string or dict")

    val = dict(val)

    val.setdefault('aliases', [])

    if 'import_path' in val:
      parts = val['import_path'].split('/')
      repo_parts = KNOWN_GIT_SERVERS.get(parts[0])
      if repo_parts is None:
        raise BegottenFileError("Unknown git server %r for %r" % (
          parts[0], name))
      repo_path = '/'.join(parts[:repo_parts+1])
      val['git_url'] = self.default_git_url_from_repo_path(repo_path)
      val['subpath'] = '/'.join(parts[repo_parts+1:])
      val['aliases'].append(val['import_path'])

      # Redirect through repo aliases:
      alias = self.get_repo_alias(repo_path)
      if alias is not None:
        if isinstance(alias, str):
          alias = {'git_url': self.default_git_url_from_repo_path(alias)}
        for attr in 'git_url', 'ref':
          if attr in alias:
            val[attr] = alias[attr]

    if 'git_url' not in val:
      raise BegottenFileError(
          "Missing 'git_url' for %r; only git is supported for now" % name)

    if 'subpath' not in val:
      val['subpath'] = ''

    if 'ref' not in val:
      val['ref'] = 'master'

    return Dep(name=name, git_url=val['git_url'], subpath=val['subpath'],
        ref=val['ref'], aliases=val['aliases'])

  def deps(self):
    if 'deps' not in self.raw:
      raise BegottenFileError("Missing 'deps' section")
    return [self.parse_dep(name, val)
        for name, val in self.raw['deps'].iteritems()]

  def set_deps(self, deps):
    def without_name(dep):
      dep = dict(dep)
      dep.pop('name')
      return dep
    self.raw['deps'] = dict((dep.name, without_name(dep)) for dep in deps)

  def repo_deps(self):
    return self.raw.get('repo_deps', {})

  def set_repo_deps(self, repo_deps):
    self.raw['repo_deps'] = repo_deps


class Builder(object):
  def __init__(self, code_root='.', use_lockfile=True):
    self.code_root = os.path.realpath(code_root)
    hsh = hashlib.sha1(self.code_root).hexdigest()[:8]
    self.code_wk = join(CODE_WORKSPACE_DIR, hsh)
    self.dep_wk = join(DEP_WORKSPACE_DIR, hsh)
    if use_lockfile:
      fn = join(self.code_root, BEGOTTEN_LOCK)
    else:
      fn = join(self.code_root, BEGOTTEN)
    try:
      self.bg = Begotten(fn)
    except BegottenFileError, e:
      print >>sys.stderr, e
      sys.exit(1)
    self.deps = self.bg.deps()
    self.repo_deps = self.bg.repo_deps()

  def _all_repos(self):
    return dict((dep.git_url, dep.ref) for dep in self.deps)

  def get_locked_refs_for_update(self, limits):
    if not limits: return {}
    try:
      bg_lock = Begotten(join(self.code_root, BEGOTTEN_LOCK))
    except IOError:
      print >>sys.stderr, "You must have a %s to do a limited update." % BEGOTTEN_LOCK
      sys.exit(1)
    except BegottenFileError, e:
      print >>sys.stderr, e
      sys.exit(1)
    deps = bg_lock.deps()
    repo_deps = bg_lock.repo_deps()
    match = lambda name: any(fnmatch.fnmatch(name, limit) for limit in limits)
    repos_to_update = set(dep.git_url for dep in deps if match(dep.name))
    n = None
    while len(repos_to_update) != n:
      n = len(repos_to_update)
      for repo in list(repos_to_update):
        repos_to_update.update(repo_deps.get(repo, []))
    return dict((dep.git_url, dep.ref) for dep in deps
                if dep.git_url not in repos_to_update)

  def setup_repos(self, fetch, limits=None):
    processed_deps = 0
    repo_versions = {}
    if fetch:
      fetched_set = set()
    else:
      fetched_set = None

    locked_refs = self.get_locked_refs_for_update(limits)

    while processed_deps < len(self.deps):
      repos_to_setup = []

      for dep in self.deps[processed_deps:]:
        have = repo_versions.get(dep.git_url)

        if dep.name.startswith('_begot_implicit/') and have is not None:
          # Implicit deps take the revision of an explicit dep from the same
          # repo, if one exists.
          dep.ref = have
          continue

        want = locked_refs.get(dep.git_url)
        if want is None:
          want = self._resolve_ref(dep.git_url, dep.ref, fetched_set)

        if have is not None:
          if have != want:
            raise DependencyError(
                "Conflicting versions for %r: have %s, want %s (%s)" % (
                dep.name, have, want, dep.ref))
        else:
          repo_versions[dep.git_url] = want
          repos_to_setup.append(dep.git_url)
        dep.ref = want

      processed_deps = len(self.deps)

      # This will add newly-found dependencies to self.deps.
      for url in repos_to_setup:
        self._setup_repo(url, repo_versions[url])

    return self

  def save_lockfile(self):
    # Should only be called when loaded from Begotten, not lockfile.
    self.bg.set_deps(self.deps)
    self.bg.set_repo_deps(self.repo_deps)
    self.bg.save(join(self.code_root, BEGOTTEN_LOCK))
    return self

  def _add_implicit_dep(self, name, val):
    dep = self.bg.parse_dep(name, val)
    self.deps.append(dep)
    return dep

  def _record_repo_dep(self, git_url):
    if self.processing_repo != git_url:
      lst = self.repo_deps.setdefault(self.processing_repo, [])
      if git_url not in lst:
        lst.append(git_url)

  def _repo_dir(self, url):
    url_hash = hashlib.sha1(url).hexdigest()
    return join(REPO_DIR, url_hash)

  def _resolve_ref(self, url, ref, fetched_set):
    repo_dir = self._repo_dir(url)
    if not os.path.isdir(repo_dir):
      print "Cloning %s" % url
      cc(['git', 'clone', '-q', url, repo_dir], cwd='/')
      # Get into detached head state so we can manipulate things without
      # worrying about messing up a branch.
      cc(['git', 'checkout', '-q', '--detach'], cwd=repo_dir)
    elif fetched_set is not None:
      if url not in fetched_set:
        print "Updating %s" % url
        cc(['git', 'fetch'], cwd=repo_dir)
        fetched_set.add(url)

    try:
      return co(['git', 'rev-parse', '--verify', 'origin/' + ref],
          cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()
    except subprocess.CalledProcessError:
      return co(['git', 'rev-parse', '--verify', ref],
          cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()

  def _setup_repo(self, url, resolved_ref):
    self.processing_repo = url
    hsh = hashlib.sha1(url).hexdigest()[:8]
    repo_dir = self._repo_dir(url)

    print "Fixing imports in %s" % url
    cc(['git', 'reset', '-q', '--hard', resolved_ref], cwd=repo_dir)

    # Match up sub-deps to our deps.
    sub_dep_map = {}
    self_deps = []
    sub_bg_path = join(repo_dir, BEGOTTEN_LOCK)
    if os.path.exists(sub_bg_path):
      sub_bg = Begotten(sub_bg_path)
      # Add implicit and explicit external dependencies.
      for sub_dep in sub_bg.deps():
        self._record_repo_dep(sub_dep.git_url)
        our_dep = self._lookup_dep_by_git_url_and_path(
            sub_dep.git_url, sub_dep.subpath)
        if our_dep is not None:
          if sub_dep.ref != our_dep.ref:
            raise DependencyError(
                "Conflict: %s depends on %s at %s, we depend on it at %s" % (
                url, sub_dep.git_url, sub_dep.ref, our_dep.ref))
          sub_dep_map[sub_dep.name] = our_dep.name
        else:
          # Include a hash of this repo identifier so that if two repos use the
          # same dep name to refer to two different things, they don't conflict
          # when we flatten deps.
          transitive_name = '_begot_transitive_%s/%s' % (hsh, sub_dep.name)
          sub_dep_map[sub_dep.name] = transitive_name
          sub_dep.name = transitive_name
          self.deps.append(sub_dep)
      # Allow relative import paths within this repo.
      for dirpath, dirnames, files in os.walk(repo_dir):
        dirnames[:] = filter(lambda n: n[0] != '.', dirnames)
        for dn in dirnames:
          relpath = join(dirpath, dn)[len(repo_dir)+1:]
          our_dep = self._lookup_dep_by_git_url_and_path(url, relpath)
          if our_dep is not None:
            sub_dep_map[relpath] = our_dep.name
          else:
            # See comment on _lookup_dep_name for re.sub rationale.
            self_name = '_begot_self_%s/%s' % (hsh, re.sub(r'\W', '_', relpath))
            sub_dep_map[relpath] = self_name
            self_deps.append(Dep(name=self_name,
              git_url=url, subpath=relpath, ref=resolved_ref, aliases=[]))

    used_rewrites = {}
    self._rewrite_imports(repo_dir, sub_dep_map, used_rewrites)
    msg = 'rewritten by begot for %s' % self.code_root
    cc(['git', 'commit', '--allow-empty', '-a', '-q', '-m', msg], cwd=repo_dir)

    # Add only the self-deps that were used, to reduce clutter.
    vals = set(used_rewrites.values())
    self.deps.extend(dep for dep in self_deps if dep.name in vals)

  def _rewrite_imports(self, repo_dir, sub_dep_map, used_rewrites):
    for dirpath, dirnames, files in os.walk(repo_dir):
      dirnames[:] = filter(lambda n: n[0] != '.', dirnames)
      for fn in files:
        if fn.endswith('.go'):
          self._rewrite_file(join(dirpath, fn), sub_dep_map, used_rewrites)

  def _rewrite_file(self, path, sub_dep_map, used_rewrites):
    # TODO: Ew ew ew.. do this using the go parser.
    code = open(path).read().splitlines(True)
    inimports = False
    for i, line in enumerate(code):
      rewrite = inimports
      if inimports and ')' in line:
          inimports = False
      elif line.startswith('import ('):
        inimports = True
      elif line.startswith('import '):
        rewrite = True
      if rewrite:
        code[i] = self._rewrite_line(line, sub_dep_map, used_rewrites)
    open(path, 'w').write(''.join(code))

  def _rewrite_line(self, line, sub_dep_map, used_rewrites):
    def repl(m):
      imp = m.group(1)
      if imp in sub_dep_map:
        imp = used_rewrites[imp] = sub_dep_map[imp]
      else:
        parts = imp.split('/')
        if parts[0] in KNOWN_GIT_SERVERS:
          imp = self._lookup_dep_name(imp)
      return '"%s"' % imp
    return re.sub(r'"([^"]+)"', repl, line)

  def _lookup_dep_name(self, imp):
    for dep in self.deps:
      if imp in dep.aliases:
        self._record_repo_dep(dep.git_url)
        return dep.name

    # Each dep turns into a symlink at build time. Packages can be nested, so we
    # might depend on 'a' and 'a/b'. If we create a symlink for 'a', we can't
    # also create 'a/b'. So rename it to 'a_b'.
    name = '_begot_implicit/' + re.sub(r'\W', '_', imp)
    dep = self._add_implicit_dep(name, imp)
    self._record_repo_dep(dep.git_url)
    return name

  def _lookup_dep_by_git_url_and_path(self, git_url, subpath):
    for dep in self.deps:
      if dep.git_url == git_url and dep.subpath == subpath:
        return dep

  def tag_repos(self):
    # Run this after setup_repos.
    for url, ref in self._all_repos().iteritems():
      cc(['git', 'tag', '--force', self._tag_hash(ref)], cwd=self._repo_dir(url))

  def _tag_hash(self, ref, cached_lf_hash=[]):
    # We want to tag the current state with a name that depends on:
    # 1. The base ref that we rewrote from.
    # 2. The full set of deps that describe how we rewrote imports.
    # The contents of Begotten.lock suffice for (2):
    if not cached_lf_hash:
      lockfile = join(self.code_root, BEGOTTEN_LOCK)
      cached_lf_hash.append(hashlib.sha1(file(lockfile).read()).hexdigest())
    lf_hash = cached_lf_hash[0]
    return '_begot_rewrote_' + hashlib.sha1(ref + lf_hash).hexdigest()

  def run(self, *args):
    self._reset_to_tags()

    # Set up code_wk.
    cbin = join(self.code_wk, 'bin')
    depsrc = join(self.dep_wk, 'src')
    empty_dep = join(depsrc, EMPTY_DEP)
    _mkdir_p(cbin, empty_dep)
    try:
      _ln_sf(cbin, join(self.code_root, 'bin'))
    except OSError:
      print >>sys.stderr, "It looks like you have an existing 'bin' directory."
      print >>sys.stderr, "Please remove it before using begot."
      sys.exit(1)
    _ln_sf(self.code_root, join(self.code_wk, 'src'))

    old_deps = set(co(['find', depsrc, '-type', 'l', '-print0']).split('\0'))
    old_deps.discard('')

    for dep in self.deps:
      path = self._setup_dep(dep)
      old_deps.discard(path)

    # Remove unexpected deps.
    if old_deps:
      for old_dep in old_deps:
        os.remove(old_dep)
      for dir in co(['find', depsrc, '-depth', '-type', 'd', '-print0']).split('\0'):
        if not dir: continue
        try:
          os.rmdir(dir)
        except OSError, e:
          if e.errno != errno.ENOTEMPTY:
            raise

    # Set up empty dep.
    #
    # The go tool tries to be helpful by not rebuilding modified code if that
    # code is in a workspace and no packages from that workspace are mentioned
    # on the command line. See cmd/go/pkg.go:isStale around line 680.
    #
    # We are explicitly managing all of the workspaces in our GOPATH and do
    # indeed want to rebuild everything when dependencies change. That is
    # required by the goal of reproducible builds: the alternative would mean
    # what you get for this build depends on the state of a previous build.
    #
    # The go tool doesn't provide any way of disabling this "helpful"
    # functionality. The simplest workaround is to always mention a package from
    # the dependency workspace on the command line. Hence, we add an empty
    # package.
    empty_go = join(empty_dep, 'empty.go')
    if not os.path.isfile(empty_go):
      open(empty_go, 'w').write('package %s\n' % EMPTY_DEP)

    # Overwrite any existing GOPATH.
    os.putenv('GOPATH', ':'.join((self.code_wk, self.dep_wk)))
    os.chdir(self.code_root)
    os.execvp(args[0], args)

  def _reset_to_tags(self):
    for url, ref in self._all_repos().iteritems():
      cc(['git', 'reset', '-q', '--hard', 'tags/' + self._tag_hash(ref)], cwd=self._repo_dir(url))

  def _setup_dep(self, dep):
    path = join(self.dep_wk, 'src', dep.name)
    target = join(self._repo_dir(dep.git_url), dep.subpath)
    _ln_sf(target, path)
    return path

  def clean(self):
    shutil.rmtree(self.dep_wk, ignore_errors=True)
    shutil.rmtree(self.code_wk, ignore_errors=True)
    _rm(join(self.code_root, 'bin'))


def get_gopath(code_root='.'):
  # This duplicates logic in Builder, but we want to just get the GOPATH without
  # parsing anything.
  while not os.path.exists(BEGOTTEN):
    if os.getcwd() == '/':
      return None
    os.chdir('..')
  hsh = hashlib.sha1(os.path.realpath('.')).hexdigest()[:8]
  code_wk = join(CODE_WORKSPACE_DIR, hsh)
  dep_wk = join(DEP_WORKSPACE_DIR, hsh)
  return ':'.join((code_wk, dep_wk))


def lock_cache():
  try:
    global _cache_lock
    _mkdir_p(BEGOT_CACHE)
    _cache_lock = file(CACHE_LOCK, 'w')
    fcntl.flock(_cache_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Leave file open for lifetime of this process and anything exec'd by this
    # process.
  except IOError:
    print >>sys.stderr, "Can't lock %r" % BEGOT_CACHE
    sys.exit(1)


def print_help(ret=1):
  print __doc__.split('---\n')[-1],
  sys.exit(ret)


def main(argv):
  lock_cache()

  try:
    cmd = argv[0]
  except IndexError:
    print_help()

  if cmd == 'update':
    Builder(use_lockfile=False).setup_repos(fetch=True, limits=argv[1:]).save_lockfile().tag_repos()
  elif cmd == 'just_rewrite':
    Builder(use_lockfile=False).setup_repos(fetch=False).save_lockfile().tag_repos()
  elif cmd == 'fetch':
    Builder(use_lockfile=True).setup_repos(fetch=False).tag_repos()
  elif cmd == 'build':
    Builder(use_lockfile=True).run('go', 'install', './...', EMPTY_DEP)
  elif cmd == 'go':
    Builder(use_lockfile=True).run('go', *argv[1:])
  elif cmd == 'exec':
    Builder(use_lockfile=True).run(*argv[1:])
  elif cmd == 'clean':
    Builder(use_lockfile=False).clean()
  elif cmd == 'gopath':
    gopath = get_gopath()
    if gopath is None:
      sys.exit(1)
    print gopath
  elif cmd == 'help':
    print_help(0)
  else:
    print >>sys.stderr, "Unknown subcommand %r" % cmd
    print_help()


if __name__ == '__main__':
  main(sys.argv[1:])

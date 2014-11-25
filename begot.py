#!/usr/bin/env python2

"""

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
system to track those changes. Rather than vendoring source within a single
repo, it maintains a family of repos (within a GitHub organization) for better
code sharing.

---

Usage:

Somewhere within your repo, put some .go files or packages in a directory with a
file named Begotten. That code will end up within a 'src' directory in a
temporary workspace created by begot, along with your dependencies.

A Begotten file is in yaml format and looks roughly like this:

  deps:
    third_party/docker: github.com/fsouza/go-dockerclient
    third_party/systemstat: bitbucket.org/bertimus9/systemstat
    third_party/gorilla/mux:
      import_path: github.com/gorilla/mux
    tddium/util:
      git_repo: git@github.com:solanolabs/tddium_go
      subpath: util
    tddium/client:
      git_url: git@github.com:solanolabs/tddium_go
      subpath: client

Things to note:
- A plain string is shorthand for {"import_path": ...}
- You can override the git url used, in a single place, which will apply to the
  whole project and all of its dependencies.

TODO: document rigorously!
TODO: document requesting a specific branch/tag/ref

In your code, you can then refer to these deps with the import path
"third_party/docker", "third_party/gorilla/mux", etc. and begot will set up the
temporary workspace correctly.

"""

import sys, os, re, subprocess, argparse, yaml, hashlib, collections, errno, shutil

BEGOTTEN = 'Begotten'
BEGOTTEN_LOCK = 'Begotten.lock'
BEGOT_WORK = '__begot_work__'

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

# TODO: only one begot process should be messing around in BEGOT_CACHE at a
# time. use a lockfile.


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

  def save(self, fn):
    yaml.dump(self.raw, open(fn, 'w'), default_flow_style=False)

  @staticmethod
  def parse_dep(name, val):
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
      val['git_url'] = 'https://' + '/'.join(parts[:repo_parts+1])
      val['subpath'] = '/'.join(parts[repo_parts+1:])
      val['aliases'].append(val['import_path'])

    if 'git_url' not in val:
      raise BegottenFileError(
          "Missing 'git_url' for %r; only git is supported for now" % name)

    if 'subpath' not in val:
      val['subpath'] = ''

    if 'ref' not in val:
      val['ref'] = 'master'

    return Dep(name=name, git_url=val['git_url'], subpath=val['subpath'],
        ref=val['ref'], aliases=val['aliases'])

  @property
  def deps(self):
    if 'deps' not in self.raw:
      raise BegottenFileError("Missing 'deps' section")
    for name, val in self.raw['deps'].iteritems():
      yield Begotten.parse_dep(name, val)

  def set_deps(self, deps):
    def without_name(dep):
      dep = dict(dep)
      dep.pop('name')
      return dep
    self.raw['deps'] = dict((dep.name, without_name(dep)) for dep in deps)


class Builder(object):
  def __init__(self, code_root='.', use_lockfile=True):
    self.code_root = os.path.realpath(code_root)
    hsh = hashlib.sha1(self.code_root).hexdigest()[:8]
    self.dep_wk = join(DEP_WORKSPACE_DIR, hsh)
    self.code_wk = join(CODE_WORKSPACE_DIR, hsh)
    if use_lockfile:
      fn = join(self.code_root, BEGOTTEN_LOCK)
    else:
      fn = join(self.code_root, BEGOTTEN)
    self.bg = Begotten(fn)
    self.deps = list(self.bg.deps)

  @property
  def _all_repos(self):
    repos = {}
    for dep in self.deps:
      repos[dep.git_url] = dep.ref
    return repos

  def setup_repos(self, update):
    # Should only be called when loaded from Begotten, not lockfile.
    processed_deps = 0
    repo_versions = {}
    if update:
      updated_set = set()
    else:
      updated_set = None

    while processed_deps < len(self.deps):
      repos_to_setup = []

      for dep in self.deps[processed_deps:]:
        have = repo_versions.get(dep.git_url)
        want = self._resolve_ref(dep.git_url, dep.ref, updated_set)
        if have is not None:
          if have != want:
            raise DependencyError(
                "Conflicting versions for %r: have %s, want %s (%s)",
                dep.name, have, want, dep.ref)
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
    self.bg.save(join(self.code_root, BEGOTTEN_LOCK))
    return self

  def _add_implicit_dep(self, name, val):
    self.deps.append(Begotten.parse_dep(name, val))

  def _repo_dir(self, url):
    url_hash = hashlib.sha1(url).hexdigest()
    return join(REPO_DIR, url_hash)

  def _resolve_ref(self, url, ref, updated_set):
    repo_dir = self._repo_dir(url)
    if not os.path.isdir(repo_dir):
      print "Cloning %s" % url
      cc(['git', 'clone', '-q', url, repo_dir], cwd='/')
      cc(['git', 'checkout', '-q', '-b', BEGOT_WORK], cwd=repo_dir)
    elif updated_set is not None:
      if url not in updated_set:
        print "Updating %s" % url
        cc(['git', 'fetch'], cwd=repo_dir)
        updated_set.add(url)

    try:
      return co(['git', 'rev-parse', '--verify', 'origin/' + ref],
          cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()
    except subprocess.CalledProcessError:
      return co(['git', 'rev-parse', '--verify', ref],
          cwd=repo_dir, stderr=open('/dev/null', 'w')).strip()

  def _setup_repo(self, url, resolved_ref):
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
      for sub_dep in sub_bg.deps:
        our_dep = self._lookup_dep_by_git_url_and_path(
            sub_dep.git_url, sub_dep.subpath)
        if our_dep is not None:
          if sub_dep.ref != our_dep.ref:
            raise DependencyError(
                "Conflict: %s depends on %s at %s, we depend on it at %s",
                url, sub_dep.git_url, sub_dep.ref, our_dep.ref)
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
          dep_name = self._lookup_dep_name(imp)
          if dep_name is not None:
            imp = dep_name
      return '"%s"' % imp
    return re.sub(r'"([^"]+)"', repl, line)

  def _lookup_dep_name(self, imp):
    for dep in self.deps:
      if imp in dep.aliases:
        return dep.name

    # Each dep turns into a symlink at build time. Packages can be nested, so we
    # might depend on 'a' and 'a/b'. If we create a symlink for 'a', we can't
    # also create 'a/b'. So rename it to 'a_b'.
    name = '_begot_implicit/' + re.sub(r'\W', '_', imp)
    self._add_implicit_dep(name, imp)
    return name

  def _lookup_dep_by_git_url_and_path(self, git_url, subpath):
    for dep in self.deps:
      if dep.git_url == git_url and dep.subpath == subpath:
        return dep

  def tag_repos(self):
    # Run this after setup_repos.
    for url, ref in self._all_repos.iteritems():
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
    _mkdir_p(cbin, depsrc)
    _ln_sf(cbin, join(self.code_root, 'bin'))
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

    # Overwrite any existing GOPATH.
    os.putenv('GOPATH', ':'.join((self.code_wk, self.dep_wk)))
    os.chdir(self.code_root)
    os.execvp(args[0], args)

  def _reset_to_tags(self):
    for url, ref in self._all_repos.iteritems():
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


def main(argv):
  cmd = argv[0]
  if cmd == 'update':
    Builder(use_lockfile=False).setup_repos(update=True).save_lockfile().tag_repos()
  elif cmd == 'rewrite':
    Builder(use_lockfile=False).setup_repos(update=False).save_lockfile().tag_repos()
  elif cmd == 'fetch':
    Builder(use_lockfile=True).setup_repos(update=False).tag_repos()
  elif cmd == 'build':
    Builder(use_lockfile=True).run('go', 'install', './...')
  elif cmd == 'go':
    Builder(use_lockfile=True).run('go', *argv[1:])
  elif cmd == 'exec':
    Builder(use_lockfile=True).run(*argv[1:])
  elif cmd == 'clean':
    Builder(use_lockfile=False).clean()
  else:
    raise Exception("Unknown subcommand %r" % cmd)


if __name__ == '__main__':
  main(sys.argv[1:])

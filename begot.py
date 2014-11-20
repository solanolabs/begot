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
here). We'd rather throw them out completely. In begot, dependency import paths
are all rewritten to use a namespace that doesn't contain any information about
where to obtain the actual code. That's in an external metadata file. Thus, we
immediately see the following advantages and disadvantages:

  Pros:
  - builds are completely reproducible
  - supporting private repos is trivial
  - you can switch to a custom fork of a dependency with a metadata change
  - no danger of multiple copies of a dependency (as long as no one in the
    dependency tree vendors things with paths rewritten to be within their repo)

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
    docker: github.com/fsouza/go-dockerclient
    systemstat: bitbucket.org/bertimus9/systemstat
    mux:
      import_path: github.com/gorilla/mux
    util:
      git_repo: git@github.com:solanolabs/tddium_go
      subpath: util
    client:
      git_url: git@github.com:solanolabs/tddium_go
      subpath: client

Things to note:
- A plain string is shorthand for {"import_path": ...}
- You can override the git url used, in a single place, which will apply to the
  whole project.

TODO: document rigorously!
TODO: document requesting a specific branch/tag/ref

In your code, you can then refer to these deps with the import path
"third_party/docker", etc. and begot will set up the temporary workspace
correctly.

"""

import sys, os, re, subprocess, argparse, yaml, hashlib, collections

BEGOTTEN = 'Begotten'
THIRD_PARTY = 'third_party'
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
    os.symlink(target, path)


Dep = collections.namedtuple('Dep', ['name', 'git_url', 'subpath', 'ref',
  'aliases'])

class Begotten(object):
  def __init__(self, fn):
    self.raw = yaml.safe_load(open(fn))

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
      # TODO: get locked ref from lockfile!
      val['ref'] = 'master'

    return Dep(name=name, git_url=val['git_url'], subpath=val['subpath'],
        ref=val['ref'], aliases=val['aliases'])

  @property
  def deps(self):
    if 'deps' not in self.raw:
      raise BegottenFileError("Missing 'deps' section")
    for name, val in self.raw['deps'].iteritems():
      yield Begotten.parse_dep(name, val)


class Builder(object):
  def __init__(self, code_root):
    self.code_root = os.path.realpath(code_root)
    hsh = hashlib.sha1(self.code_root).hexdigest()[:8]
    self.dep_wk = join(DEP_WORKSPACE_DIR, hsh)
    self.code_wk = join(CODE_WORKSPACE_DIR, hsh)
    self.bg = Begotten(join(self.code_root, BEGOTTEN))
    self.deps = list(self.bg.deps)

  def build(self, pkgs):
    cbin = join(self.code_wk, 'bin')
    tp = join(self.dep_wk, 'src', THIRD_PARTY)
    _mkdir_p(cbin, tp)
    _ln_sf(cbin, join(self.code_root, 'bin'))
    _ln_sf(self.code_root, join(self.code_wk, 'src'))

    processed_deps = 0
    repo_versions = {}

    while processed_deps < len(self.deps):
      repos_to_setup = []

      for dep in self.deps[processed_deps:]:
        have = repo_versions.get(dep.git_url)
        if have is not None:
          if have != dep.ref:
            raise DependencyError("Conflicting versions for %r: %r vs %r",
                dep.name, have, dep.ref)
        else:
          repo_versions[dep.git_url] = dep.ref
          repos_to_setup.append((dep.git_url, dep.ref))

      processed_deps = len(self.deps)

      for url, ref in repos_to_setup:
        self._setup_repo(url, ref)

    for dep in self.deps:
      self._setup_dep(dep)

    args = ['go', 'install', pkgs]
    env = dict(os.environ)
    env['GOPATH'] = ':'.join((self.code_wk, self.dep_wk))
    cc(args=args, cwd=self.code_root, env=env)

  def _add_implicit_dep(self, name, val):
    self.deps.append(Begotten.parse_dep(name, val))

  def _repo_dir(self, url):
    url_hash = hashlib.sha1(url).hexdigest()
    return join(REPO_DIR, url_hash)

  def _setup_repo(self, url, ref):
    repo_dir = self._repo_dir(url)
    if not os.path.isdir(repo_dir):
      print "Fetching %s" % url
      cc(['git', 'clone', url, repo_dir], cwd='/')
      cc(['git', 'checkout', '-b', BEGOT_WORK], cwd=repo_dir)

    # TODO: skip reset and rewrite if already done
    cc(['git', 'reset', '-q', '--hard', ref], cwd=repo_dir)
    self._rewrite_imports(repo_dir)

  def _rewrite_imports(self, repo_dir):
    for dirpath, _, files in os.walk(repo_dir):
      for fn in files:
        if not fn.endswith('.go'):
          continue
        self._rewrite_file(join(dirpath, fn))

  def _rewrite_file(self, path):
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
        code[i] = self._rewrite_line(line)
    open(path, 'w').write(''.join(code))

  def _rewrite_line(self, line):
    def repl(m):
      imp = m.group(1)
      parts = imp.split('/')
      if parts[0] in KNOWN_GIT_SERVERS:
        dep_name = self._lookup_dep_name(imp)
        if dep_name is not None:
          imp = 'third_party/' + dep_name
      return '"%s"' % imp
    return re.sub(r'"([^"]+)"', repl, line)

  def _lookup_dep_name(self, imp):
    for dep in self.deps:
      if imp in dep.aliases:
        return dep.name

    #print "Found implicit dependency %s" % imp
    name = '_implicit_%s' % re.sub(r'\W', '_', imp)
    self._add_implicit_dep(name, imp)
    return name

  def _setup_dep(self, dep):
    path = join(self.dep_wk, 'src', THIRD_PARTY, dep.name)
    target = join(self._repo_dir(dep.git_url), dep.subpath)
    _ln_sf(target, path)


def main(argv):
  cmd = argv[0]
  if cmd == 'build':
    builder = Builder('.')
    builder.build('./...')
  elif cmd == 'update':
    pass # TODO: implement


if __name__ == '__main__':
  main(sys.argv[1:])

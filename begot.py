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

import sys, os, re, subprocess, argparse, yaml, hashlib

BEGOTTEN = 'Begotten'
THIRD_PARTH = 'third_party'

# Known public servers and how many path components form the repo name.
KNOWN_GIT_SERVERS = {
  'github.com': 2,
  'bitbucket.org': 2,
}

join = os.path.join
HOME = os.getenv('HOME')
BEGOT_CACHE = os.getenv('BEGOT_CACHE') or join(HOME, '.cache', 'begot')
WORKSPACE_DIR = join(BEGOT_CACHE, 'work')
REPO_DIR = join(BEGOT_CACHE, 'repo')


class BegottenFileError(Exception): pass

def _mkdir_p(*dirs):
  for d in dirs:
    if not os.path.isdir(d):
      os.makedirs(d)
def _ln_sf(target, path):
  if not os.path.islink(path) or os.readlink(path) != target:
    os.remove(path)
    os.symlink(target, path)


Dep = namedtuple('Dep', ['name', 'git_url', 'subpath', 'ref'])

class Begotten(object):
  def __init__(self, fn):
    self.raw = yaml.safe_load(open(fn))

  @property
  def deps(self):
    if 'deps' not in self.raw:
      raise BegottenFileError("Missing 'deps' section")
    for name, val in self.raw['deps'].iteritems():
      if isinstance(val, string):
        val = {'import_path': val}
      if not isinstance(val, dict):
        raise BegottenFileError("Dependency value must be string or dict")

      val = dict(val)

      if 'import_path' in val:
        parts = val['import_path'].split('/')
        repo_parts = KNOWN_GIT_SERVERS.get(parts[0])
        if repo_parts is None:
          raise BegottenFileError("Unknown git server %r for %r", parts[0], name)
        val['git_url'] = 'https://' + '/'.join(parts[:repo_parts])
        val['subpath'] = '/'.join(parts[repo_parts:])

      if 'git_url' not in val:
        raise BegottenFileError(
            "Missing 'git_url' for %r; only git is supported for now", name)

      if 'ref' not in val:
        # TODO: get locked ref from lockfile!
        ref = 'master'

      yield Dep(name=name, git_url=val['git_url'], subpath=val['subpath'],
          ref=val['ref'])


class Builder(object):
  def __init__(self, code_root):
    self.code_root = os.path.realpath(code_root)
    hsh = hashlib.sha1(self.code_root).hexdigest()[:6]
    self.workspace = join(WORKSPACE_DIR, hsh)

  def build(self, pkgs):
    bin = join(self.workspace, 'bin')
    src = join(self.workspace, 'src')

    _mkdir_p(bin, src)
    _ln_sf(bin, join(self.code_root, 'bin'))

    bg = Begotten(join(self.code_root, BEGOTTEN))

    for dep in bg.deps:
      self._setup_dep(dep)

    args = ['go', 'install', pkgs]
    env = dict(os.environ)
    env['GOPATH'] = self.workspace
    subprocess.check_call(args=args, env=env)

  def _setup_dep(self, dep):
    print dep


def main(argv):
  cmd = argv[0]
  if cmd == 'build':
    builder = Builder('.')
    builder.build('./...')



if __name__ == '__main__':
  main(sys.argv[1:])

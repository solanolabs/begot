#!/usr/bin/env python2
#
# Copyright (c) 2014 Solano Labs Inc.  All Rights Reserved.

import sys, os, fcntl, re, subprocess, hashlib, errno, shutil, fnmatch, yaml
import tempfile, unittest, traceback, contextlib

cc = subprocess.check_call
co = subprocess.check_output
join = os.path.join

BEGOT = os.path.realpath(join(os.path.dirname(__file__), 'begot.py'))


@contextlib.contextmanager
def chdir(path):
  cwd = os.getcwd()
  try:
    os.chdir(path)
    yield
  finally:
    os.chdir(cwd)

def mkdir_p(*dirs):
  for d in dirs:
    if d and not os.path.isdir(d):
      os.makedirs(d)

def begot(*args):
  print '+', 'begot', ' '.join(args)
  out = co((BEGOT,) + args)
  for line in out.splitlines():
    print ' ', line

def begot_err(*args, **kwargs):
  p = subprocess.Popen((BEGOT,) + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  out, _ = p.communicate()
  for line in out.splitlines():
    print ' ', line
  retval = p.wait()
  if retval == 0:
    raise subprocess.CalledProcessError(
        "begot didn't exit with an error as expected")

  expect = kwargs.get('expect')
  if isinstance(expect, str):
    assert expect in out
  elif hasattr(expect, 'search'):
    assert expect.search(out)


def git(*args):
  print '+', 'git', ' '.join(args)
  out = co(('git',) + args)
  for line in out.splitlines():
    print ' ', line
  return out

def write_begotten(deps):
  data = {'deps': deps}
  yaml.safe_dump(data, open('Begotten', 'w'))

def write_files(files):
  for name, contents in files.iteritems():
    mkdir_p(os.path.dirname(name))
    open(name, 'w').write(contents)

def repo_path(path):
  return join(repodir, 'begot.test', path)

def make_nonbegot_repo(path, files):
  path = repo_path(path)
  mkdir_p(path)
  with chdir(path):
    git('init', '-q')
    write_files(files)
    git('add', '--all', '.')
    git('commit', '-q', '-m', 'initial commit')

def make_begot_repo(path, deps, files):
  path = repo_path(path)
  mkdir_p(path)
  with chdir(path):
    git('init', '-q')
    write_begotten(deps)
    write_files(files)

    begot('update')

    git('add', '--all', '.')
    git('commit', '-q', '-m', 'initial commit')

def make_begot_workdir(deps, files):
  write_begotten(deps)
  write_files(files)

def clear_dir(d):
  if os.path.exists(d):
    shutil.rmtree(d)
  os.mkdir(d)

def clear_cache():
  clear_dir(cachedir)

def read_lockfile_deps(expected_count):
  deps = yaml.safe_load(open('Begotten.lock'))['deps']
  assert len(deps) == expected_count
  return deps

def clear_cache_fetch_twice_and_build():
  # First clear the cache and fetch to ensure fetch works from an empty cache.
  clear_cache()
  begot('fetch')
  # Then fetch again to ensure it works from a full cache.
  begot('fetch')
  # Then make sure we can build.
  begot('build')

def stripiws(s):
  return re.sub(r'^\s+', '', s, flags=re.MULTILINE)

def count(it):
  c = 0
  for i in it:
    if i:
      c += 1
  return c


NUMBER_GO = stripiws(r"""
  package number
  const NUMBER = 42
""")

DEP_IN_SAME_REPO_GO = stripiws(r"""
  package number2
  import "begot.test/user/repo/otherpkg"
  const NUMBER2 = number.NUMBER + 12
""")

DEP_IN_OTHER_REPO_GO = stripiws(r"""
  package number2
  import "begot.test/otheruser/repo"
  const NUMBER2 = number.NUMBER + 12
""")

USE_BEGOT_DEP_GO = stripiws(r"""
  package number2
  import "tp/otherdep"
  const NUMBER2 = number.NUMBER + 12
""")

MAIN_GO = stripiws(r"""
  package main
  import "fmt"
  import "tp/dep"
  func main() {
    fmt.Printf("The answer is %s.", number.NUMBER)
  }
""")

MAIN2_GO = stripiws(r"""
  package main
  import "fmt"
  import "tp/dep"
  func main() {
    fmt.Printf("The answer is %s.", number2.NUMBER2)
  }
""")

MAIN3_GO = stripiws(r"""
  package main
  import "fmt"
  import "tp/dep"
  import "tp/otherdep"
  func main() {
    fmt.Printf("The answer is %s.", number2.NUMBER2 + number3.NUMBER3)
  }
""")

# update/fetch situations:

def test_empty_begotfile():
  make_begot_workdir({}, {})

  begot('update')

  read_lockfile_deps(0)

  clear_cache_fetch_twice_and_build()


def test_one_dep_at_repo_root():
  make_nonbegot_repo('user/repo',
      {'code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert not dep.get('subpath') # null or empty string

  clear_cache_fetch_twice_and_build()


def test_one_dep_with_subpath():
  make_nonbegot_repo('user/repo',
      {'pkg/code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'

  clear_cache_fetch_twice_and_build()


def test_dep_as_git_url_and_subpath():
  make_nonbegot_repo('user/repo',
      {'pkg/code.go': NUMBER_GO})

  url = 'file://' + repo_path('user/repo')
  make_begot_workdir(
      {'tp/dep': {'git_url': url, 'subpath': 'pkg'}},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'

  clear_cache_fetch_twice_and_build()


def test_one_dep_with_implicit_dep_in_same_repo():
  make_nonbegot_repo('user/repo',
      {
        'pkg/code.go': DEP_IN_SAME_REPO_GO,
        'otherpkg/code.go': NUMBER_GO,
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main2.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)

  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'

  _, otherdep = deps.popitem()
  assert otherdep['git_url'] == dep['git_url']
  assert otherdep['subpath'] == 'otherpkg'

  clear_cache_fetch_twice_and_build()


def test_one_dep_with_implicit_dep_in_other_repo():
  make_nonbegot_repo('otheruser/repo',
      {
        'code.go': NUMBER_GO,
      })

  make_nonbegot_repo('user/repo',
      {
        'code.go': DEP_IN_OTHER_REPO_GO,
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main2.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)

  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')

  _, otherdep = deps.popitem()
  assert otherdep['git_url'].endswith('otheruser/repo')

  clear_cache_fetch_twice_and_build()


#   one non-begot dep with an implicit dep with an implicit dep
#   FIXME

def test_begot_dep():
  make_begot_repo('user/repo',
      {},
      {'code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert not dep.get('subpath') # null or empty string

  clear_cache_fetch_twice_and_build()


def test_begot_dep_with_subpath():
  make_begot_repo('user/repo',
      {},
      {'pkg/code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'

  clear_cache_fetch_twice_and_build()


def test_begot_dep_with_begot_dep_different_name(): # both have subpaths
  make_begot_repo('user/otherrepo',
      {},
      {'pkg2/code.go': NUMBER_GO})

  make_begot_repo('user/repo',
      {'tp/otherdep': 'begot.test/user/otherrepo/pkg2'},
      {'pkg/code.go': USE_BEGOT_DEP_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'
  _, otherdep = deps.popitem()
  assert otherdep['git_url'].endswith('user/otherrepo')
  assert otherdep['subpath'] == 'pkg2'

  clear_cache_fetch_twice_and_build()


def test_begot_dep_with_begot_dep_same_name():
  make_begot_repo('user/otherrepo',
      {},
      {'pkg2/code.go': NUMBER_GO})

  make_begot_repo('user/repo',
      {'tp/dep': 'begot.test/user/otherrepo/pkg2'},
      {'pkg/code.go': stripiws(r"""
          package number2
          import "tp/dep"
          const NUMBER2 = number.NUMBER + 12
      """)})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)
  assert all('tp/dep' in name for name in deps.keys())
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'
  _, otherdep = deps.popitem()
  assert otherdep['git_url'].endswith('user/otherrepo')
  assert otherdep['subpath'] == 'pkg2'

  clear_cache_fetch_twice_and_build()


def test_self_dep():
  make_begot_workdir(
      {},
      {
        'app/main.go': MAIN_GO,
        'tp/dep/code.go': NUMBER_GO,
      })

  begot('update')

  read_lockfile_deps(0)

  clear_cache_fetch_twice_and_build()


def test_begot_dep_with_self_dep():
  make_begot_repo('user/repo',
      {},
      {
        'code.go': USE_BEGOT_DEP_GO,
        'tp/otherdep/morecode.go': NUMBER_GO,
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)
  dep = deps.pop('tp/dep')
  selfdep_name, selfdep = deps.popitem()
  assert 'begot_self' in selfdep_name
  assert dep['git_url'] == selfdep['git_url']

  clear_cache_fetch_twice_and_build()


def test_begot_dep_with_two_self_deps_prefix():
  # Note that one of these package paths is a prefix of the other.
  # The replacement of slash by underscore lets this work.
  make_begot_repo('user/repo',
      {},
      {
        'code.go': stripiws(r"""
          package number2
          import "self"
          import "self/self"
          const NUMBER2 = self1.N + self2.M
        """),
        'self/code.go': stripiws(r"""
          package self1
          const N = 25
        """),
        'self/self/code.go': stripiws(r"""
          package self2
          const M = 17
        """),
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(3)
  dep = deps.pop('tp/dep')
  for _ in range(2):
    selfdep_name, selfdep = deps.popitem()
    assert 'begot_self' in selfdep_name
    assert dep['git_url'] == selfdep['git_url']

  clear_cache_fetch_twice_and_build()


def test_two_begot_deps_with_two_self_deps():
  # Note that both refer to "self". The hash in _begot_self_ lets this work.
  make_begot_repo('user/repo',
      {},
      {
        'code.go': stripiws(r"""
          package number2
          import "self"
          const NUMBER2 = self1.N + 13
        """),
        'self/code.go': stripiws(r"""
          package self1
          const N = 6
        """),
      })

  make_begot_repo('user/otherrepo',
      {},
      {
        'code.go': stripiws(r"""
          package number3
          import "self"
          const NUMBER3 = self3.O + 5
        """),
        'self/code.go': stripiws(r"""
          package self3
          const O = 19
        """),
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo',
       'tp/otherdep': 'begot.test/user/otherrepo'},
      {'app/main.go': MAIN3_GO})

  begot('update')

  deps = read_lockfile_deps(4)
  assert 2 == count('begot_self' in name for name in deps.keys())
  assert 2 == count(name.endswith('/self') for name in deps.keys())
  assert 2 == count(dep['git_url'].endswith('user/repo') for dep in deps.values())
  assert 2 == count(dep['git_url'].endswith('user/otherrepo') for dep in deps.values())

  clear_cache_fetch_twice_and_build()


def test_two_implicit_deps_prefix():
  # Note that one of these two implicit deps is a prefix of the other.
  # The replacement of slash by underscore lets this work.
  make_nonbegot_repo('user/otherrepo',
      {
        'code.go': stripiws(r"""
          package implicit1
          const N = 23
        """),
        'pkg/code.go': stripiws(r"""
          package implicit2
          const M = 19
        """),
      })

  make_nonbegot_repo('user/repo',
      {
        'code.go': stripiws(r"""
          package number
          import "begot.test/user/otherrepo"
          import "begot.test/user/otherrepo/pkg"
          const NUMBER = implicit1.N + implicit2.M
        """),
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main2.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(3)

  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert all(dep['git_url'].endswith('user/otherrepo') for dep in deps.values())
  assert 1 == count(dep['subpath'] == 'pkg' for dep in deps.values())
  assert 1 == count(not dep['subpath'] for dep in deps.values())

  clear_cache_fetch_twice_and_build()


def test_two_begot_deps_with_deps_with_same_name():
  # Note that the two begot deps use tp/subdep to refer to different things.
  # The hash in _begot_transitive_ lets this work.
  make_nonbegot_repo('depuser/repo',
      {
        'code.go': stripiws(r"""
          package dep1
          const N = 33
        """),
      })

  make_nonbegot_repo('depuser/otherrepo',
      {
        'code.go': stripiws(r"""
          package dep2
          const M = 11
        """),
      })

  make_begot_repo('user/repo',
      {'tp/subdep': 'begot.test/depuser/repo'},
      {
        'code.go': stripiws(r"""
          package number2
          import "tp/subdep"
          const NUMBER2 = dep1.N + 5
        """),
      })

  make_begot_repo('user/otherrepo',
      {'tp/subdep': 'begot.test/depuser/otherrepo'},
      {
        'code.go': stripiws(r"""
          package number3
          import "tp/subdep"
          const NUMBER3 = dep2.M + 6
        """),
      })

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo',
       'tp/otherdep': 'begot.test/user/otherrepo'},
      {'app/main.go': MAIN3_GO})

  begot('update')

  deps = read_lockfile_deps(4)
  assert 2 == count('begot_transitive' in name for name in deps.keys())
  assert 2 == count(name.endswith('tp/subdep') for name in deps.keys())
  assert 2 == count('depuser' in dep['git_url'] for dep in deps.values())

  clear_cache_fetch_twice_and_build()


def test_conflict_between_two_deps():
  make_nonbegot_repo('user/repo', {'code.go': NUMBER_GO})

  with chdir(repo_path('user/repo')):
    git('tag', 'one')
    open('code.go', 'a').write('\n//comment\n')
    git('commit', '-q', '-a', '-m', 'comment')
    git('tag', 'two')

  make_begot_workdir(
      {'tp/dep1': {'import_path': 'begot.test/user/repo', 'ref': 'one'},
       'tp/dep2': {'import_path': 'begot.test/user/repo', 'ref': 'two'}},
      {})

  begot_err('update', expect="Conflicting versions")


def test_conflict_between_dep_and_dep_of_dep():
  make_nonbegot_repo('otheruser/repo',
      {'code.go': NUMBER_GO})

  with chdir(repo_path('otheruser/repo')):
    git('tag', 'one')
    open('code.go', 'a').write('\n//comment\n')
    git('commit', '-q', '-a', '-m', 'comment')
    git('tag', 'two')

  make_begot_repo('user/repo',
      {'tp/otherdep': {'import_path': 'begot.test/otheruser/repo', 'ref': 'two'}},
      {})

  make_begot_workdir(
      {'tp/dep': {'import_path': 'begot.test/user/repo'},
       'tp/otherdep': {'import_path': 'begot.test/otheruser/repo', 'ref': 'one'}},
      {'app/main.go': MAIN_GO})

  begot_err('update', expect="Conflict:")


def test_nonconflict_between_dep_with_ref_and_implicit_dep():
  make_nonbegot_repo('otheruser/repo',
      {'code.go': NUMBER_GO})

  with chdir(repo_path('otheruser/repo')):
    git('tag', 'one')
    open('code.go', 'a').write('\n//comment\n')
    git('commit', '-q', '-a', '-m', 'comment')
    # 'master' is now different than 'one'
    one = git('rev-parse', 'one').strip()
    master = git('rev-parse', 'master').strip()
    assert one != master

  make_nonbegot_repo('user/repo',
      {'code.go': DEP_IN_OTHER_REPO_GO})

  make_begot_workdir(
      {'tp/dep': {'import_path': 'begot.test/user/repo'},
       'tp/otherdep': {'import_path': 'begot.test/otheruser/repo', 'ref': 'one'}},
      {'app/main.go': MAIN2_GO})

  begot('update')

  deps = read_lockfile_deps(2)
  otherdep = deps.pop('tp/otherdep')
  assert otherdep['git_url'].endswith('otheruser/repo')
  assert otherdep['ref'] == one

  clear_cache_fetch_twice_and_build()


def test_dep_with_branch():
  make_nonbegot_repo('user/repo',
      {'pkg/code.go': NUMBER_GO})

  with chdir(repo_path('user/repo')):
    git('checkout', '-b', 'branch')
    open('pkg/code.go', 'a').write('\n//comment\n')
    git('commit', '-q', '-a', '-m', 'comment')
    branch = git('rev-parse', 'branch').strip()

  make_begot_workdir(
      {'tp/dep': {'import_path': 'begot.test/user/repo/pkg', 'ref': 'branch'}},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['ref'] == branch

  clear_cache_fetch_twice_and_build()


def test_dep_with_commit_id():
  make_nonbegot_repo('user/repo',
      {'pkg/code.go': NUMBER_GO})

  with chdir(repo_path('user/repo')):
    ref = git('rev-parse', 'master').strip()
    open('pkg/code.go', 'a').write('\n//comment\n')
    git('commit', '-q', '-a', '-m', 'comment')
    assert ref != git('rev-parse', 'master').strip()

  make_begot_workdir(
      {'tp/dep': {'import_path': 'begot.test/user/repo/pkg', 'ref': ref}},
      {'app/main.go': MAIN_GO})

  begot('update')

  deps = read_lockfile_deps(1)
  dep = deps.pop('tp/dep')
  assert dep['ref'] == ref

  clear_cache_fetch_twice_and_build()


def test_repo_alias_simple():
  make_nonbegot_repo('otheruser/repo',
      {'code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  aliases = {'repo_aliases': {'begot.test/user/repo': 'begot.test/otheruser/repo'}}
  yaml.safe_dump(aliases, open('Begotten', 'a'))

  begot('update')

  deps = read_lockfile_deps(1)
  assert all(dep['git_url'].endswith('otheruser/repo') for dep in deps.values())

  clear_cache_fetch_twice_and_build()


def test_repo_alias_with_implicit_dep_on_self():
  make_nonbegot_repo('otheruser/repo',
      # imports begot.test/user/repo/otherpkg, but gets redirected to self.
      {'pkg/code.go': DEP_IN_SAME_REPO_GO,
       'otherpkg/code.go': NUMBER_GO})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo/pkg'},
      {'app/main.go': MAIN2_GO})

  aliases = {'repo_aliases': {'begot.test/user/repo': 'begot.test/otheruser/repo'}}
  yaml.safe_dump(aliases, open('Begotten', 'a'))

  begot('update')

  deps = read_lockfile_deps(2)
  assert all(dep['git_url'].endswith('otheruser/repo') for dep in deps.values())

  clear_cache_fetch_twice_and_build()


#   limited update of one dep
#   FIXME

#   limited update of dep with implicit dep
#   FIXME

# build:

#   build two projects that depend on a repo at different revs
#   FIXME

#   build before fetch and get error
#   FIXME

#   change in project causes rebuilding
#   FIXME

#   change in self-package causes rebuilding
#   FIXME

#   change in dep causes rebuilding
#   FIXME


# clean
#   FIXME

# gopath
#   FIXME

# fetch/build with wrong file version number
#   FIXME




def global_setup():
  global tmpdir, cachedir, repodir
  tmpdir = tempfile.mkdtemp(prefix='begot_test_tmp')
  cachedir = join(tmpdir, 'cache')
  repodir = join(tmpdir, 'repo')
  os.putenv('BEGOT_CACHE', cachedir)
  os.putenv('BEGOT_TEST_REPOS', repodir)

def global_teardown():
  os.chdir('/')
  shutil.rmtree(tmpdir)

def run_tests():
  passed = failed = 0
  for name, func in globals().iteritems():
    if not callable(func): continue
    if not name.startswith('test'): continue

    # clean up
    clear_cache()
    clear_dir(repodir)

    # every test gets a new working directory
    workdir = join(tmpdir, name)
    os.mkdir(workdir)
    os.chdir(workdir)

    print "=" * len(name)
    print name
    print "-" * len(name)
    try:
      func()
      print 'PASS'
      passed += 1
    except KeyboardInterrupt:
      raise
    except:
      print 'FAIL'
      traceback.print_exc()
      failed += 1
  print
  print '%d passed, %d failed' % (passed, failed)
  return int(failed > 0)


def main():
  try:
    global_setup()
    retval = run_tests()
    sys.exit(retval)
  finally:
    global_teardown()


if __name__ == '__main__':
  main()

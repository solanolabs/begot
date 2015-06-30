#!/usr/bin/env python2
#
# Copyright (c) 2014 Solano Labs Inc.  All Rights Reserved.

import sys, os, fcntl, re, subprocess, hashlib, errno, shutil, fnmatch, yaml
import tempfile, unittest, traceback, contextlib, time

cc = subprocess.check_call
co = subprocess.check_output
join = os.path.join

BEGOT = os.path.realpath(join(os.path.dirname(__file__), 'begot'))


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
  try:
    out = co((BEGOT,) + args)
  except subprocess.CalledProcessError, e:
    for line in e.output.splitlines():
      print '!', line
    raise
  for line in out.splitlines():
    print ' ', line
  return out

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
    try:
      shutil.rmtree(d)
    except OSError: # handle weird race conditions
      shutil.rmtree(d)
  os.mkdir(d)

def clear_cache():
  clear_dir(cachedir)

def read_lockfile_deps(expected_count):
  deps = yaml.safe_load(open('Begotten.lock'))['resolved_deps']
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
    fmt.Printf("The answer is %d.", number.NUMBER)
  }
""")

MAIN2_GO = stripiws(r"""
  package main
  import "fmt"
  import "tp/dep"
  func main() {
    fmt.Printf("The answer is %d.", number2.NUMBER2)
  }
""")

MAIN3_GO = stripiws(r"""
  package main
  import "fmt"
  import "tp/dep"
  import "tp/otherdep"
  func main() {
    fmt.Printf("The answer is %d.", number2.NUMBER2 + number3.NUMBER3)
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
  dep = deps.pop('tp/dep')
  assert dep['git_url'].endswith('user/repo')
  assert dep['subpath'] == 'pkg'
  _, otherdep = deps.popitem()
  # TODO: reenable when source works right
  #assert any('transitive dep of tp/dep' in s for s in otherdep['source'])
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
  assert any('self dep' in s for s in selfdep['source'])
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
    assert any('self dep' in s for s in selfdep['source'])
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

  deps = read_lockfile_deps(4).values()
  assert 2 == count(any('self dep' in s for s in dep['source']) for dep in deps)
  assert 2 == count(dep['git_url'].endswith('user/repo') for dep in deps)
  assert 2 == count(dep['git_url'].endswith('user/otherrepo') for dep in deps)

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

  deps = read_lockfile_deps(4).values()
  # TODO: reenable when source works right
  #assert 2 == count(any('transitive dep of tp/subdep' in s for s in dep['source']) for dep in deps)
  assert 2 == count('depuser' in dep['git_url'] for dep in deps)

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

  begot_err('update', expect="Conflicting versions")


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
  assert otherdep['commit_id'] == one

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
  assert dep['commit_id'] == branch

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
  assert dep['commit_id'] == ref

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


def test_full_update():
  make_nonbegot_repo('user/repo1', {'a': 'a'})
  make_nonbegot_repo('user/repo2', {'a': 'a'})

  make_begot_workdir(
      {'tp/dep1': 'begot.test/user/repo1',
       'tp/dep2': 'begot.test/user/repo2'},
      {})

  begot('update')

  before = read_lockfile_deps(2)
  oneb = before['tp/dep1']['commit_id']
  twob = before['tp/dep2']['commit_id']

  for repo in 'user/repo1', 'user/repo2':
    with chdir(repo_path(repo)):
      open('b', 'w').write('b')
      git('add', '.')
      git('commit', '-q', '-m', 'b')

  begot('update')

  after = read_lockfile_deps(2)
  onea = after['tp/dep1']['commit_id']
  twoa = after['tp/dep2']['commit_id']

  assert oneb != onea
  assert twob != twoa


def test_limited_update():
  make_nonbegot_repo('user/repo1', {'a': 'a'})
  make_nonbegot_repo('user/repo2', {'a': 'a'})

  make_begot_workdir(
      {'tp/dep1': 'begot.test/user/repo1',
       'tp/dep2': 'begot.test/user/repo2',
       'tp/dep3': 'begot.test/user/repo2/subdir'},
      {})

  begot('update')

  before = read_lockfile_deps(3)
  oneb = before['tp/dep1']['commit_id']
  twob = before['tp/dep2']['commit_id']
  threeb = before['tp/dep3']['commit_id']

  for repo in 'user/repo1', 'user/repo2':
    with chdir(repo_path(repo)):
      open('b', 'w').write('b')
      git('add', '.')
      git('commit', '-q', '-m', 'b')

  begot('update', 'tp/dep2')

  after = read_lockfile_deps(3)
  onea = after['tp/dep1']['commit_id']
  twoa = after['tp/dep2']['commit_id']
  threea = after['tp/dep3']['commit_id']

  assert oneb == onea
  assert twob != twoa
  assert threeb != threea # updated because dep2 was updated


def test_limited_update_with_implicit_dep():
  make_nonbegot_repo('otheruser/repo', {'a': 'a'})
  make_nonbegot_repo('user/repo1', {
    'code.go': DEP_IN_OTHER_REPO_GO,
    })
  make_nonbegot_repo('user/repo2', {'a': 'a'})

  make_begot_workdir(
      {'tp/dep1': 'begot.test/user/repo1',
       'tp/dep2': 'begot.test/user/repo2'},
      {})

  begot('update')

  before = read_lockfile_deps(3)
  oneb = before.pop('tp/dep1')['commit_id']
  twob = before.pop('tp/dep2')['commit_id']
  otherb = before.popitem()[1]['commit_id']

  for repo in 'user/repo1', 'user/repo2', 'otheruser/repo':
    with chdir(repo_path(repo)):
      open('b', 'w').write('b')
      git('add', '.')
      git('commit', '-q', '-m', 'b')

  begot('update', 'tp/dep1')

  after = read_lockfile_deps(3)
  onea = after.pop('tp/dep1')['commit_id']
  twoa = after.pop('tp/dep2')['commit_id']
  othera = after.popitem()[1]['commit_id']

  assert oneb != onea
  assert twob == twoa
  assert otherb != othera # updated because dep1 was updated


def test_limited_update_with_explicit_dep():
  make_nonbegot_repo('otheruser/repo', {'a': 'a'})
  make_begot_repo('user/repo1',
      {'otherdep': 'begot.test/otheruser/repo'},
      {'a': 'a'})
  make_nonbegot_repo('user/repo2', {'a': 'a'})

  make_begot_workdir(
      {'tp/dep1': 'begot.test/user/repo1',
       'tp/dep2': 'begot.test/user/repo2'},
      {})

  begot('update')

  before = read_lockfile_deps(3)
  oneb = before.pop('tp/dep1')['commit_id']
  twob = before.pop('tp/dep2')['commit_id']
  otherb = before.popitem()[1]['commit_id']

  for repo in 'otheruser/repo', 'user/repo1', 'user/repo2':
    with chdir(repo_path(repo)):
      open('b', 'w').write('b')
      if os.path.exists('Begotten'):
        begot('update')
      git('add', '.')
      git('commit', '-q', '-m', 'b')

  begot('update', 'tp/dep1')

  after = read_lockfile_deps(3)
  onea = after.pop('tp/dep1')['commit_id']
  twoa = after.pop('tp/dep2')['commit_id']
  othera = after.popitem()[1]['commit_id']

  assert oneb != onea
  assert twob == twoa
  assert otherb != othera # updated because dep1 was updated


def test_fetch_before_build():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')
  clear_cache()
  begot_err('build', expect='missing local commit')


def test_fetch_can_fetch():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')

  # snapshot cache
  os.rename(cachedir, cachedir+'.tmp')

  with chdir(repo_path('user/repo')):
    open('number.go', 'a').write("\n")
    git('commit', '-q', '-a', '-m', 'foo')

  begot('update')

  # restore snapshot
  clear_cache()
  os.rename(cachedir+'.tmp', cachedir)

  begot('fetch')


def test_no_rebuild():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')
  begot('build')
  timeb = os.stat('bin/app').st_mtime

  time.sleep(1.5)
  begot('build')
  timea = os.stat('bin/app').st_mtime

  assert timeb == timea


def test_rebuild_on_local_change():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')
  begot('build')
  timeb = os.stat('bin/app').st_mtime

  time.sleep(1.5)
  open('app/main.go', 'a').write("\n")
  begot('build')
  timea = os.stat('bin/app').st_mtime

  assert timeb != timea


def test_rebuild_on_dep_change():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  begot('update')
  begot('build')
  timeb = os.stat('bin/app').st_mtime

  time.sleep(1.5)
  with chdir(repo_path('user/repo')):
    open('number.go', 'a').write("\n")
    git('commit', '-q', '-a', '-m', 'foo')

  begot('update')
  begot('build')
  timea = os.stat('bin/app').st_mtime

  assert timeb != timea


def test_rebuild_on_self_dep_change():
  make_begot_workdir(
      {},
      {
        'app/main.go': MAIN_GO,
        'tp/dep/code.go': NUMBER_GO,
      })

  begot('update')
  begot('build')
  timeb = os.stat('bin/app').st_mtime

  time.sleep(1.5)
  open('tp/dep/code.go', 'a').write("\n")

  begot('update')
  begot('build')
  timea = os.stat('bin/app').st_mtime

  assert timeb != timea


def test_build_consistency():
  make_nonbegot_repo('user/repo',
      {'number.go': "package number\nconst NUMBER = 42\n"})

  t1, t2 = repo_path('t1'), repo_path('t2')

  for t in t1, t2:
    mkdir_p(t)
    with chdir(t):
      make_begot_workdir(
          {'tp/dep': 'begot.test/user/repo'},
          {'app/main.go': MAIN_GO})
      begot('update')

    with chdir(repo_path('user/repo')):
      open('number.go', 'w').write("package number\nconst NUMBER = 44\n")
      git('commit', '-q', '-a', '--allow-empty', '-m', 'foo')

  for t, ans in zip([t1, t2, t1, t2], [42, 44, 42, 44]):
    with chdir(t):
      begot('clean')
      begot('build')
      assert co('./bin/app') == ('The answer is %d.' % ans)


def test_build_consistency_across_repo_rename():
  """This situation is a little tricky, but can come up when switching between
  git branches in the same repo when different branches use the same dep name to
  refer to two different origin repos. The key is that Begotten.lock changes
  (from one correct version to another) without running begot fetch (which would
  reset and rewrite files and cause a rebuild that way). We use rename to
  emulate switching branches. See commit 200400b.
  """
  make_nonbegot_repo('user/repo',
      {'number.go': "package number\nconst NUMBER = 42\n"})
  make_nonbegot_repo('user/repo2',
      {'number.go': "package number\nconst NUMBER = 44\n"})

  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})
  begot('update')

  os.rename('Begotten', 'orig-Begotten')
  os.rename('Begotten.lock', 'orig-Begotten.lock')

  write_begotten({'tp/dep': 'begot.test/user/repo2'})
  begot('update')

  begot('build')
  assert co('./bin/app') == 'The answer is 44.'

  os.rename('orig-Begotten', 'Begotten')
  os.rename('orig-Begotten.lock', 'Begotten.lock')

  begot('build')
  assert co('./bin/app') == 'The answer is 42.'


def test_clean_and_gopath():
  make_nonbegot_repo('user/repo', {'number.go': NUMBER_GO})
  make_begot_workdir(
      {'tp/dep': 'begot.test/user/repo'},
      {'app/main.go': MAIN_GO})

  gopath = begot('gopath').strip()
  begot('update')
  begot('build')
  linkdest = os.readlink('bin')
  for elt in gopath.split(':'):
    assert os.path.isdir(elt)

  begot('clean')
  assert not os.path.exists('bin')
  assert not os.path.exists(linkdest)
  for elt in gopath.split(':'):
    assert not os.path.isdir(elt)


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

def run_tests(shard=0, count=1, argv=None):
  passed = failed = 0
  failed_names = []
  for i, (name, func) in enumerate(sorted(globals().items())):
    if not callable(func): continue
    if not name.startswith('test'): continue
    if (i % count) != shard: continue
    if argv and name not in argv: continue

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
      failed_names.append(name)
  print
  print '%d passed, %d failed' % (passed, failed)
  print
  if failed_names:
    print 'Failing tests:', ' '.join(sorted(failed_names))
  return int(failed > 0)


def main():
  try:
    global_setup()
    shard, count = map(int, os.getenv('SHARD', '0/1').split('/'))
    retval = run_tests(shard, count, sys.argv[1:])
    sys.exit(retval)
  finally:
    global_teardown()


if __name__ == '__main__':
  main()


begot: begot.go code_version.go
	env GOPATH=$(CURDIR)/bootstrap go build $^

code_version.go: code_version.go.current
	if [ ! -e $@ -o "`cat $<`" != "`cat $@`" ]; then cp -f $^ $@; fi

.PHONY: code_version.go.current
code_version.go.current:
	/bin/echo -e "package main\nconst CODE_VERSION=\"`git describe --abbrev=8 --dirty --always --tags`\"" > $@

test:
	./begot_test.py

clean:
	rm begot


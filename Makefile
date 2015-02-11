
begot: begot.go
	env GOPATH=$(CURDIR)/bootstrap go build $^

test:
	./begot_test.py

clean:
	rm begot


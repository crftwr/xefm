# XeFM's Linux test image (glibc): the dependencies, not the source.
#
# The source is mounted read-only at run time rather than copied in, so a test
# run needs no rebuild and cannot write into the working tree. Only
# requirements.txt is baked, which means the pip layer is rebuilt exactly when
# the dependencies change and reused every other time.
#
#   make test-linux
#
# See doc/dev/LINUX_TESTING_SYSTEM.md.
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

# libarchive13 is the runtime package. libarchive-dev is deliberately *not*
# installed: the runtime package alone is the state a user's machine is in, and
# whether XeFM can find a library in that state is one of the things this image
# is here to answer. (On Debian it can — ldconfig knows the soname. On musl it
# cannot; see Dockerfile.musl.)
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends libarchive13 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --quiet -r /tmp/requirements.txt \
 && pip install --no-cache-dir --quiet pytest pytest-timeout pytest-xdist \
 && rm /tmp/requirements.txt

# The source mount is read-only, so nothing may be written beside it: no
# bytecode, and no .pytest_cache either — the cache plugin only warns, but a
# warning that appears on every run is a warning nobody reads.
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
CMD ["python", "-m", "pytest", "test/", "-q", "-p", "no:cacheprovider"]

# The read-only Git server Argo CD on kind pulls from (git://, no credentials, laptop only).
FROM alpine:3.22
RUN apk add --no-cache git-daemon
USER nobody
ENTRYPOINT ["git", "daemon", "--reuseaddr", "--base-path=/git", "--export-all", "--verbose", "/git"]

# Puma: several worker processes, one thread each. Ruby's GVL limits a process
# to roughly one core, and the sqlite3 gem holds the GVL while a query runs, so
# extra threads can't overlap queries; they only queue behind each other and
# add switching. One thread per worker cut p99 at 3,000 users from ~590 ms to
# ~140 ms (raw data layer).
#
#   WEB_CONCURRENCY=4 RAILS_MAX_THREADS=1 bundle exec puma
workers Integer(ENV.fetch("WEB_CONCURRENCY", 4))
threads_count = Integer(ENV.fetch("RAILS_MAX_THREADS", 1))
threads threads_count, threads_count
bind "tcp://127.0.0.1:#{ENV.fetch("PORT", 7881)}"
environment ENV.fetch("RAILS_ENV", "production")

# Load the app once, then fork: workers share its memory copy-on-write.
preload_app!

# SQLite connections must not cross a fork; each worker opens its own.
before_worker_boot do
  Db.reset!
  ResponseCache.reset!
end

pidfile ENV["PIDFILE"] if ENV["PIDFILE"]

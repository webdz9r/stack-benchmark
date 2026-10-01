require_relative "boot"

require "rails"
# Pick the frameworks you want:
require "active_model/railtie"
# require "active_job/railtie"
require "active_record/railtie"
# require "active_storage/engine"
require "action_controller/railtie"
# require "action_mailer/railtie"
# require "action_mailbox/engine"
# require "action_text/engine"
require "action_view/railtie"
# require "action_cable/engine"
# require "rails/test_unit/railtie"

# Require the gems listed in Gemfile, including any gems
# you've limited to :test, :development, or :production.
Bundler.require(*Rails.groups)

module BackendRails
  class Application < Rails::Application
    # Initialize configuration defaults for originally generated Rails version.
    config.load_defaults 8.1

    # Please, add to the `ignore` list any other `lib` subdirectories that do
    # not contain `.rb` files, or that should not be reloaded or eager loaded.
    # Common ones are `templates`, `generators`, or `middleware`, for example.
    config.autoload_lib(ignore: %w[assets tasks])

    # Configuration for the application, engines, and railties goes here.
    #
    # These settings can be overridden in specific environments using the files
    # in config/environments, which are processed later.
    #
    # config.time_zone = "Central Time (US & Canada)"
    # config.eager_load_paths << Rails.root.join("extras")

    # Only loads a smaller set of middleware suitable for API only apps.
    # Middleware like session, flash, cookies can be added back manually.
    # Skip views, helpers and assets when generating a new resource.
    config.api_only = true

    # gzip like the other backends: zlib's default level (6), bodies of 32 bytes
    # or more, and static files too (so it goes in front of ActionDispatch::Static).
    # Rack::ContentLength fills in the length the size check needs.
    config.middleware.insert_before ActionDispatch::Static, Rack::Deflater,
      if: ->(_env, _status, headers, _body) { (len = headers["content-length"]).nil? || len.to_i >= 32 }
    config.middleware.insert_after Rack::Deflater, Rack::ContentLength
    # Rack::ETag hashes every response body; the response cache sets its own
    # ETags on the cached endpoints, as the other backends do.
    config.middleware.delete Rack::ETag

    # Serve the built frontend, like the Rust binary does.
    config.paths["public"] = File.expand_path(ENV.fetch("STATIC_DIR", "../../frontend/dist"), File.join(__dir__, ".."))
    config.public_file_server.enabled = true
  end
end

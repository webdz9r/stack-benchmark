class ApplicationController < ActionController::API
  rescue_from AppError do |e|
    render_json({ "error" => e.message }, e.status)
  end

  rescue_from ActiveRecord::RecordNotFound do
    render_json({ "error" => "not found" }, 404)
  end

  rescue_from JSON::ParserError do |e|
    render_json({ "error" => "invalid JSON: #{e.message}" }, 400)
  end

  def not_found
    render_json({ "error" => "not found" }, 404)
  end

  private

  # RAILS_DATA=activerecord uses ActiveRecord models; otherwise the shared SQL
  # goes straight to the sqlite3 gem.
  STORE = ENV["RAILS_DATA"] == "activerecord" ? ActiveRecordStore.new : RawStore.new

  def store = STORE
  def cache = ResponseCache.instance

  def render_json(data, status = 200)
    render body: JSON.generate(data), content_type: "application/json", status: status
  end

  # Serve from the response cache (see ResponseCache).
  def render_cached(key, &compute)
    status, headers, body = cache.json(request, key, &compute)
    headers.each { |k, v| response.set_header(k, v) }
    status == 304 ? head(:not_modified) : render(body: body, content_type: "application/json")
  end

  # The parsed JSON body, parsed directly (no params wrapping or filtering),
  # like the other backends. An empty body is nil.
  def json_body
    raw = request.raw_post
    raw.nil? || raw.empty? ? nil : JSON.parse(raw)
  end

  # A path id that isn't an integer is a 400, not a 500 (spec §7).
  def path_id
    Integer(params[:id], 10)
  rescue ArgumentError, TypeError
    raise AppError.new(400, "invalid id")
  end

  def int_param(name)
    value = params[name]
    value.nil? || value == "" ? nil : Integer(value, 10)
  rescue ArgumentError
    raise AppError.new(400, "#{name} must be an integer")
  end
end

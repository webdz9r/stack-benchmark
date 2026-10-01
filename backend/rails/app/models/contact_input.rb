# Request body validation; same rules as the Rust backend.
module ContactInput
  TAG_COLORS = %w[slate red orange amber green teal sky indigo violet pink].freeze
  ADDRESS_FIELDS = %i[street city region postal_code country].freeze

  module_function

  # Trim fields, drop empty rows, and reject obviously bad input.
  def contact(body)
    raise AppError.validation("expected a JSON object") unless body.is_a?(Hash)

    c = %w[first_name last_name company job_title notes].to_h { |f| [f.to_sym, str(body[f], f).strip] }
    raise AppError.validation("a name or company is required") if c[:first_name].empty? && c[:last_name].empty? && c[:company].empty?

    c[:favorite] = body["favorite"] == true
    birthday = str(body["birthday"], "birthday").strip
    c[:birthday] = birthday.empty? ? nil : birthday
    raise AppError.validation("birthday must be YYYY-MM-DD") if c[:birthday] && !iso_date?(c[:birthday])

    c[:emails] = labeled(body["emails"], "emails")
    c[:phones] = labeled(body["phones"], "phones")
    c[:emails].each do |e|
      user, at, domain = e[:value].partition("@")
      unless !at.empty? && !user.empty? && domain.include?(".") && !e[:value].match?(/\s/)
        raise AppError.validation("'#{e[:value]}' is not a valid email")
      end
    end

    c[:addresses] = list(body["addresses"], "addresses").filter_map do |a|
      a = {} unless a.is_a?(Hash)
      row = { label: label(str(a["label"], "label")) }
      ADDRESS_FIELDS.each { |f| row[f] = str(a[f.to_s], f.to_s).strip }
      row if ADDRESS_FIELDS.any? { |f| !row[f].empty? }
    end

    c[:tag_ids] = list(body["tag_ids"], "tag_ids").map { Integer(_1) }.uniq.sort
    c
  rescue ArgumentError, TypeError
    raise AppError.validation("tag_ids must be integers")
  end

  def tag(body)
    name = str(body.is_a?(Hash) ? body["name"] : nil, "name").strip
    raise AppError.validation("tag name is required") if name.empty?
    raise AppError.validation("tag name must be 40 characters or fewer") if name.length > 40
    color = body["color"]
    raise AppError.validation("unknown tag color '#{color}'") if color && !TAG_COLORS.include?(color)
    { name:, color: }
  end

  def str(value, field)
    return "" if value.nil?
    raise AppError.validation("#{field} must be a string") unless value.is_a?(String)
    value
  end

  def list(value, field)
    return [] if value.nil?
    raise AppError.validation("#{field} must be a list") unless value.is_a?(Array)
    value
  end

  def labeled(rows, field)
    list(rows, field).filter_map do |r|
      r = {} unless r.is_a?(Hash)
      value = str(r["value"], "value").strip
      { label: label(str(r["label"], "label")), value: } unless value.empty?
    end
  end

  def label(l) = l.strip.downcase.then { _1.empty? ? "other" : _1 }

  def iso_date?(s)
    m = /\A(\d{4})-(\d{2})-(\d{2})\z/.match(s) or return false
    (1..12).cover?(m[2].to_i) && (1..31).cover?(m[3].to_i)
  end
end

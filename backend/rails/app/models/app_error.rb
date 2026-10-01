# An error with an HTTP status; rendered as {"error": message}.
class AppError < StandardError
  attr_reader :status

  def initialize(status, message)
    super(message)
    @status = status
  end

  def self.not_found = new(404, "not found")
  def self.validation(message) = new(422, message)
  def self.conflict(message) = new(409, message)
end

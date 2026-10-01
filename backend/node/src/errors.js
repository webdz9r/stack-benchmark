/** An error with an HTTP status; rendered as {"error": message}. */
export class AppError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
  static notFound() { return new AppError(404, 'not found') }
  static validation(message) { return new AppError(422, message) }
  static conflict(message) { return new AppError(409, message) }
}

export const isConstraintError = (e) => typeof e?.code === 'string' && e.code.startsWith('SQLITE_CONSTRAINT')

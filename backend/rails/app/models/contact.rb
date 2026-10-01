class Contact < ApplicationRecord
  ORDER = Arel.sql("contacts.sort_key COLLATE NOCASE, contacts.first_name COLLATE NOCASE, contacts.id")

  # Timestamps are ISO-8601 strings (the schema's format, shared with the
  # other backends), so they're set here rather than by Rails.
  self.record_timestamps = false
  attribute :favorite, :boolean

  has_many :emails, -> { order(:position) }, dependent: :delete_all
  has_many :phones, -> { order(:position) }, dependent: :delete_all
  has_many :addresses, -> { order(:position) }, dependent: :delete_all
  has_many :contact_tags, dependent: :delete_all
  has_many :tags, -> { order(Arel.sql("tags.name COLLATE NOCASE")) }, through: :contact_tags

  before_create { self.created_at = self.updated_at = Contact.now }
  before_update { self.updated_at = Contact.now }
  # Runs after the has_many autosaves, so the search document sees the new rows.
  after_save :refresh_search_index
  before_destroy { self.class.connection.exec_delete("DELETE FROM contacts_fts WHERE rowid = ?", "FTS", [id]) }

  scope :sorted, -> { order(ORDER) }
  scope :search, ->(q) {
    fts = Repo.fts_query(q)
    fts ? where("contacts.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)", fts) : all
  }
  scope :tagged, ->(tag_id) { tag_id.nil? ? all : where(id: ContactTag.where(tag_id: tag_id).select(:contact_id)) }
  scope :favorites, ->(only) { only ? where(favorite: true) : all }
  scope :filtered, ->(q:, tag:, favorite:) { search(q).tagged(tag).favorites(favorite) }

  def self.now = Time.now.utc.strftime("%Y-%m-%dT%H:%M:%S.%LZ")

  # Replace name, details and child rows from validated input (see ContactInput).
  def assign_input(c)
    assign_attributes(c.slice(:first_name, :last_name, :company, :job_title, :birthday, :notes, :favorite))
    self.emails = c[:emails].each_with_index.map { |e, i| Email.new(e.merge(position: i)) }
    self.phones = c[:phones].each_with_index.map { |p, i| Phone.new(p.merge(position: i)) }
    self.addresses = c[:addresses].each_with_index.map { |a, i| Address.new(a.merge(position: i)) }
    missing = c[:tag_ids] - Tag.where(id: c[:tag_ids]).pluck(:id)
    raise AppError.validation("tag #{missing.first} does not exist") if missing.any?
    self.tag_ids = c[:tag_ids]
  end

  def as_api_json
    as_json(only: %i[id first_name last_name company job_title birthday notes favorite]).merge(
      "emails" => emails.map { _1.as_json(only: %i[label value]) },
      "phones" => phones.map { _1.as_json(only: %i[label value]) },
      "addresses" => addresses.map { _1.as_json(only: %i[label street city region postal_code country]) },
      "tags" => tags.map { _1.as_json(only: %i[id name color]) },
      "created_at" => created_at,
      "updated_at" => updated_at
    )
  end

  def as_summary_json
    as_json(only: %i[id first_name last_name company job_title favorite]).merge(
      "email" => emails.first&.value,
      "phone" => phones.first&.value,
      "tag_ids" => contact_tags.map(&:tag_id).sort
    )
  end

  private

  # Rebuild this contact's search document from its current rows.
  def refresh_search_index
    conn = self.class.connection
    conn.exec_delete("DELETE FROM contacts_fts WHERE rowid = ?", "FTS", [id])
    conn.exec_insert(<<~SQL, "FTS", [id])
      INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
      SELECT c.id,
             c.first_name || ' ' || c.last_name,
             c.company || ' ' || c.job_title,
             coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
             coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
             coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                       FROM addresses WHERE contact_id = c.id), ''),
             c.notes
      FROM contacts c WHERE c.id = ?
    SQL
  end
end

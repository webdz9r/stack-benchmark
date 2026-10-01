# Plain synchronous SQL; the same statements as the Rust backend's repo.rs.
module Repo
  MAX_PAGE = 200
  CONTACT_ORDER = "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id"
  NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

  module_function

  # ---------------------------------------------------------------- contacts

  # Free text -> safe FTS5 query: each word a quoted prefix term.
  # `jo smi` -> `"jo"* "smi"*`. A word is made of Unicode letters, marks and
  # numbers (general categories L*, M*, N*), plus `@ . '`.
  def fts_query(text)
    return nil if text.nil? || text.empty?
    terms = text.split(/[^\p{L}\p{M}\p{N}@.']+/).reject(&:empty?)
    return nil if terms.empty?
    terms.map { |t| %("#{t.gsub('"', '""')}"*) }.join(" ")
  end

  def filters(q:, tag:, favorite:)
    clauses = []
    args = []
    if (fts = fts_query(q))
      clauses << "c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)"
      args << fts
    end
    unless tag.nil?
      clauses << "c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)"
      args << tag
    end
    clauses << "c.favorite = 1" if favorite
    [clauses.empty? ? "" : "WHERE #{clauses.join(' AND ')}", args]
  end

  def list_contacts(db, q:, tag:, favorite:, limit:, offset:)
    limit = (limit || 50).clamp(1, MAX_PAGE)
    offset = [offset || 0, 0].max
    where, args = filters(q:, tag:, favorite:)

    total = db.query_row("SELECT count(*) FROM contacts c #{where}", *args)[0]
    rows = db.query_all(<<~SQL, *args, limit, offset)
      SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
             (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
             (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
             (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
      FROM contacts c
      #{where}
      ORDER BY #{CONTACT_ORDER}
      LIMIT ? OFFSET ?
    SQL
    items = rows.map do |r|
      {
        "id" => r[0], "first_name" => r[1], "last_name" => r[2], "company" => r[3],
        "job_title" => r[4], "favorite" => r[5] == 1, "email" => r[6], "phone" => r[7],
        "tag_ids" => r[8] ? r[8].split(",").map(&:to_i) : []
      }
    end
    { "items" => items, "total" => total, "limit" => limit, "offset" => offset }
  end

  # Where each file letter starts in the sorted, filtered list. Buckets are
  # contiguous and sort like the list ('#' < 'A'..'Z' < '~'), so offsets are
  # running totals; '~' (after Z) is reported as '#'.
  def list_letters(db, q:, tag:, favorite:)
    where, args = filters(q:, tag:, favorite:)
    buckets = db.query_all(
      "SELECT c.sort_letter, count(*) FROM contacts c #{where} GROUP BY c.sort_letter ORDER BY c.sort_letter", *args
    )
    letters = []
    offset = 0
    buckets.each do |letter, count|
      if letter == "~"
        if (hash = letters.find { |l| l["letter"] == "#" })
          hash["count"] += count
        else
          letters << { "letter" => "#", "offset" => offset, "count" => count }
        end
      else
        letters << { "letter" => letter, "offset" => offset, "count" => count }
      end
      offset += count
    end
    letters
  end

  def get_contact(db, id)
    r = db.query_row(<<~SQL, id)
      SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite, created_at, updated_at
      FROM contacts WHERE id = ?
    SQL
    raise AppError.not_found unless r

    labeled = ->(table) {
      db.query_all("SELECT label, value FROM #{table} WHERE contact_id = ? ORDER BY position", id)
        .map { |label, value| { "label" => label, "value" => value } }
    }
    {
      "id" => r[0], "first_name" => r[1], "last_name" => r[2], "company" => r[3], "job_title" => r[4],
      "birthday" => r[5], "notes" => r[6], "favorite" => r[7] == 1,
      "emails" => labeled.("emails"),
      "phones" => labeled.("phones"),
      "addresses" => db.query_all(<<~SQL, id).map { |a| %w[label street city region postal_code country].zip(a).to_h },
        SELECT label, street, city, region, postal_code, country
        FROM addresses WHERE contact_id = ? ORDER BY position
      SQL
      "tags" => db.query_all(<<~SQL, id).map { |t| { "id" => t[0], "name" => t[1], "color" => t[2] } },
        SELECT t.id, t.name, t.color FROM tags t
        JOIN contact_tags ct ON ct.tag_id = t.id
        WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE
      SQL
      "created_at" => r[8],
      "updated_at" => r[9]
    }
  end

  def insert_contact(tx, c)
    tx.run(<<~SQL, c[:first_name], c[:last_name], c[:company], c[:job_title], c[:birthday], c[:notes], c[:favorite] ? 1 : 0)
      INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    SQL
    id = tx.last_insert_row_id
    write_children(tx, id, c)
    refresh_fts(tx, id)
    id
  end

  def update_contact(tx, id, c)
    changed = tx.run(<<~SQL, c[:first_name], c[:last_name], c[:company], c[:job_title], c[:birthday], c[:notes], c[:favorite] ? 1 : 0, id)
      UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
          birthday = ?, notes = ?, favorite = ?, updated_at = #{NOW}
      WHERE id = ?
    SQL
    raise AppError.not_found if changed.zero?
    %w[emails phones addresses contact_tags].each { |t| tx.run("DELETE FROM #{t} WHERE contact_id = ?", id) }
    write_children(tx, id, c)
    refresh_fts(tx, id)
  end

  def set_favorite(tx, id, favorite)
    changed = tx.run("UPDATE contacts SET favorite = ?, updated_at = #{NOW} WHERE id = ?", favorite ? 1 : 0, id)
    raise AppError.not_found if changed.zero?
  end

  def delete_contact(tx, id)
    # Children go via ON DELETE CASCADE; the FTS table has no foreign key.
    tx.run("DELETE FROM contacts_fts WHERE rowid = ?", id)
    raise AppError.not_found if tx.run("DELETE FROM contacts WHERE id = ?", id).zero?
  end

  def write_children(tx, id, c)
    c[:emails].each_with_index do |e, i|
      tx.run("INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, e[:label], e[:value], i)
    end
    c[:phones].each_with_index do |p, i|
      tx.run("INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, p[:label], p[:value], i)
    end
    c[:addresses].each_with_index do |a, i|
      tx.run(<<~SQL, id, a[:label], a[:street], a[:city], a[:region], a[:postal_code], a[:country], i)
        INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      SQL
    end
    c[:tag_ids].each do |tag_id|
      tx.run("INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", id, tag_id)
    rescue SQLite3::ConstraintException
      raise AppError.validation("tag #{tag_id} does not exist")
    end
  end

  # Rebuild one contact's search document from its current rows.
  def refresh_fts(tx, id)
    tx.run("DELETE FROM contacts_fts WHERE rowid = ?", id)
    tx.run(<<~SQL, id)
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

  # ---------------------------------------------------------------- tags

  def list_tags(db)
    db.query_all(<<~SQL).map { |r| { "id" => r[0], "name" => r[1], "color" => r[2], "contact_count" => r[3] } }
      SELECT t.id, t.name, t.color, count(ct.contact_id)
      FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
      GROUP BY t.id ORDER BY t.name COLLATE NOCASE
    SQL
  end

  def get_tag(db, id)
    r = db.query_row("SELECT id, name, color FROM tags WHERE id = ?", id)
    raise AppError.not_found unless r
    { "id" => r[0], "name" => r[1], "color" => r[2] }
  end

  def insert_tag(tx, t)
    tx.run("INSERT INTO tags (name, color) VALUES (?, ?)", t[:name], t[:color] || "slate")
    get_tag(tx, tx.last_insert_row_id)
  rescue SQLite3::ConstraintException
    raise AppError.conflict("a tag named '#{t[:name]}' already exists")
  end

  def update_tag(tx, id, t)
    changed =
      begin
        tx.run("UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?", t[:name], t[:color], id)
      rescue SQLite3::ConstraintException
        raise AppError.conflict("a tag named '#{t[:name]}' already exists")
      end
    raise AppError.not_found if changed.zero?
    get_tag(tx, id)
  end

  def delete_tag(tx, id)
    raise AppError.not_found if tx.run("DELETE FROM tags WHERE id = ?", id).zero?
  end

  # ---------------------------------------------------------------- stats

  def stats(db)
    contacts, favorites = db.query_row("SELECT count(*), coalesce(sum(favorite), 0) FROM contacts")
    { "contacts" => contacts, "favorites" => favorites }
  end
end

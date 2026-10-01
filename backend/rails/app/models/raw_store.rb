# Data layer that sends the shared SQL straight to the sqlite3 gem (see Db,
# Repo). The default; RAILS_DATA=activerecord selects ActiveRecordStore.
class RawStore
  def db = Db.instance

  def list_contacts(**query) = Repo.list_contacts(db.reader, **query)
  def list_letters(**filters) = Repo.list_letters(db.reader, **filters)
  def get_contact(id) = Repo.get_contact(db.reader, id)

  def create_contact(c)
    db.transaction { |tx| Repo.get_contact(tx, Repo.insert_contact(tx, c)) }
  end

  def update_contact(id, c)
    db.transaction do |tx|
      Repo.update_contact(tx, id, c)
      Repo.get_contact(tx, id)
    end
  end

  def set_favorite(id, favorite) = db.transaction { |tx| Repo.set_favorite(tx, id, favorite) }
  def delete_contact(id) = db.transaction { |tx| Repo.delete_contact(tx, id) }

  def list_tags = Repo.list_tags(db.reader)
  def create_tag(t) = db.transaction { |tx| Repo.insert_tag(tx, t) }
  def update_tag(id, t) = db.transaction { |tx| Repo.update_tag(tx, id, t) }
  def delete_tag(id) = db.transaction { |tx| Repo.delete_tag(tx, id) }

  def stats = Repo.stats(db.reader)
end

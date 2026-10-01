# Data layer written the usual Rails way: ActiveRecord models, associations,
# scopes and preloading (RAILS_DATA=activerecord). Returns the same JSON shapes
# as RawStore, so the two can be benchmarked against each other.
class ActiveRecordStore
  MAX_PAGE = 200

  def list_contacts(q:, tag:, favorite:, limit:, offset:)
    limit = (limit || 50).clamp(1, MAX_PAGE)
    offset = [offset || 0, 0].max
    scope = Contact.filtered(q:, tag:, favorite:)
    contacts = scope.sorted.limit(limit).offset(offset).includes(:emails, :phones, :contact_tags)
    { "items" => contacts.map(&:as_summary_json), "total" => scope.count, "limit" => limit, "offset" => offset }
  end

  # Offsets are running totals of per-letter counts; see Repo.list_letters.
  def list_letters(q:, tag:, favorite:)
    counts = Contact.filtered(q:, tag:, favorite:).group(:sort_letter).order(:sort_letter).count
    letters = []
    offset = 0
    counts.each do |letter, count|
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

  def get_contact(id)
    Contact.includes(:emails, :phones, :addresses, :tags).find(id).as_api_json
  end

  def create_contact(c)
    Contact.transaction do
      contact = Contact.new
      contact.assign_input(c)
      contact.save!
      get_contact(contact.id)
    end
  end

  def update_contact(id, c)
    Contact.transaction do
      contact = Contact.find(id)
      contact.assign_input(c)
      contact.save!
      get_contact(id)
    end
  end

  def set_favorite(id, favorite)
    Contact.find(id).update!(favorite:)
  end

  def delete_contact(id)
    Contact.transaction { Contact.find(id).destroy! }
  end

  def list_tags
    Tag.with_counts.map { |t| t.as_json(only: %i[id name color]).merge("contact_count" => t.contact_count) }
  end

  def create_tag(t)
    Tag.create!(name: t[:name], color: t[:color] || "slate").as_json(only: %i[id name color])
  rescue ActiveRecord::RecordNotUnique
    raise AppError.conflict("a tag named '#{t[:name]}' already exists")
  end

  def update_tag(id, t)
    tag = Tag.find(id)
    tag.update!({ name: t[:name], color: t[:color] }.compact)
    tag.as_json(only: %i[id name color])
  rescue ActiveRecord::RecordNotUnique
    raise AppError.conflict("a tag named '#{t[:name]}' already exists")
  end

  def delete_tag(id)
    Tag.transaction { Tag.find(id).destroy! }
  end

  def stats
    { "contacts" => Contact.count, "favorites" => Contact.where(favorite: true).count }
  end
end

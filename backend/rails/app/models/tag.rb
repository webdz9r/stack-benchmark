class Tag < ApplicationRecord
  has_many :contact_tags, dependent: :delete_all
  has_many :contacts, through: :contact_tags

  scope :sorted, -> { order(Arel.sql("tags.name COLLATE NOCASE")) }

  def self.with_counts
    left_joins(:contact_tags).group(:id).sorted.select("tags.*, COUNT(contact_tags.contact_id) AS contact_count")
  end
end

class ContactTag < ApplicationRecord
  self.primary_key = %i[contact_id tag_id]
  belongs_to :contact
  belongs_to :tag
end

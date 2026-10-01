class ContactsController < ApplicationController
  def index
    f = filters
    query = f.merge(limit: int_param(:limit), offset: int_param(:offset))
    if f[:tag].nil? && !f[:favorite] && Repo.fts_query(f[:q]).nil?
      # Unfiltered pages walk the sort index and are cheap; not worth caching.
      return render_json(store.list_contacts(**query))
    end
    render_cached("list|#{filter_key(f)}|#{query[:limit]}|#{query[:offset]}") { store.list_contacts(**query) }
  end

  def letters
    f = filters
    render_cached("letters|#{filter_key(f)}") { store.list_letters(**f) }
  end

  def show
    render_json(store.get_contact(contact_id))
  end

  def create
    render_json(store.create_contact(ContactInput.contact(json_body)), 201)
  end

  def update
    render_json(store.update_contact(contact_id, ContactInput.contact(json_body)))
  end

  def favorite
    value = json_body&.dig("favorite")
    raise AppError.validation("favorite must be true or false") unless [true, false].include?(value)
    store.set_favorite(contact_id, value)
    head :no_content
  end

  def destroy
    store.delete_contact(contact_id)
    head :no_content
  end

  private

  def contact_id = path_id

  def filters
    favorite = params[:favorite]
    raise AppError.new(400, "favorite must be true or false") unless [nil, "true", "false"].include?(favorite)
    { q: params[:q], tag: int_param(:tag), favorite: favorite == "true" }
  end

  def filter_key(f) = "#{Repo.fts_query(f[:q])}|#{f[:tag]}|#{f[:favorite]}"
end

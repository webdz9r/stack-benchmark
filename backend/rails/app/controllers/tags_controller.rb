class TagsController < ApplicationController
  def index
    render_cached("tags") { store.list_tags }
  end

  def create
    render_json(store.create_tag(ContactInput.tag(json_body)), 201)
  end

  def update
    render_json(store.update_tag(path_id, ContactInput.tag(json_body)))
  end

  def destroy
    store.delete_tag(path_id)
    head :no_content
  end
end

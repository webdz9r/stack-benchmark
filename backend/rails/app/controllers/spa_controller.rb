class SpaController < ApplicationController
  def index
    index = Rails.public_path.join("index.html")
    return not_found unless index.exist?
    send_file index, type: "text/html", disposition: "inline"
  end
end

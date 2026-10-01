Rails.application.routes.draw do
  scope "/api" do
    get "health", to: "stats#health"
    get "stats", to: "stats#show"

    get "contacts/letters", to: "contacts#letters"
    resources :contacts, only: %i[index show create update destroy] do
      put "favorite", on: :member
    end
    resources :tags, only: %i[index create update destroy]

    # Unknown /api paths get a JSON 404.
    match "*path", to: "application#not_found", via: :all
  end

  # Anything else that isn't a file in the built frontend gets its index.html
  # (the SPA fallback).
  get "*path", to: "spa#index", format: false
end

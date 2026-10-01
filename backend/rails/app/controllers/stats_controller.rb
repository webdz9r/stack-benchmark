class StatsController < ApplicationController
  def show
    render_cached("stats") { store.stats }
  end

  def health
    render plain: "ok"
  end
end

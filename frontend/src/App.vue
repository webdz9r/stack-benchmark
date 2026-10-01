<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from './api'
import { displayName } from './format'
import Sidebar from './components/Sidebar.vue'
import ContactList from './components/ContactList.vue'
import ContactCard from './components/ContactCard.vue'
import ContactForm from './components/ContactForm.vue'

const PAGE = 60

// filter.view is 'all' | 'favorites' | 'tag'
const filter = reactive({ view: 'all', tagId: null, q: '' })
const tags = ref([])
const stats = ref({ contacts: 0, favorites: 0 })

// The list holds a window of the full sorted result: rows [start, start + items.length).
// It usually starts at 0, but jumping to a letter can start it anywhere, and it
// then grows in either direction as you scroll.
const list = reactive({ items: [], start: 0, total: 0, letters: [], loading: false, error: '' })
// Bumped when the filters change, so the list scrolls back to the top.
const listKey = ref(0)
let listRequest = 0

const selectedId = ref(null)
const selected = ref(null)
const mode = ref('view') // 'view' | 'edit' | 'new'
const toast = ref(null)

const tagsById = computed(() => Object.fromEntries(tags.value.map((t) => [t.id, t])))
const filterTitle = computed(() => {
  if (filter.view === 'favorites') return 'Favorites'
  if (filter.view === 'tag') return tagsById.value[filter.tagId]?.name ?? 'Tag'
  return 'All contacts'
})
// On narrow screens the list and the detail pane take turns.
const showingDetail = computed(() => mode.value !== 'view' || selectedId.value !== null)

function notify(message, tone = 'info') {
  toast.value = { message, tone, key: Date.now() }
  setTimeout(() => { if (toast.value?.message === message) toast.value = null }, 3500)
}

function currentFilters() {
  return {
    q: filter.q.trim(),
    tag: filter.view === 'tag' ? filter.tagId : null,
    favorite: filter.view === 'favorites',
  }
}

/** Replace the window with rows starting at `offset`, and refresh the letter index. */
async function loadList({ offset = 0, limit = PAGE } = {}) {
  const request = ++listRequest
  list.loading = true
  list.error = ''
  try {
    const filters = currentFilters()
    const [page, letters] = await Promise.all([
      api.listContacts({ ...filters, offset, limit }),
      api.contactLetters(filters),
    ])
    if (request !== listRequest) return // a newer load superseded this one
    if (!page.items.length && offset > 0) {
      // The window fell off the end (e.g. after deletes); start over at the top.
      list.loading = false
      return loadList()
    }
    list.items = page.items
    list.start = offset
    list.total = page.total
    list.letters = letters
  } catch (e) {
    if (request === listRequest) list.error = e.message
  } finally {
    if (request === listRequest) list.loading = false
  }
}

/** Reload the current window in place, e.g. after an edit, keeping your spot. */
function reloadList() {
  return loadList({ offset: list.start, limit: Math.min(Math.max(list.items.length, PAGE), 200) })
}

/** Grow the window by one page before or after it. */
async function loadAdjacent(direction) {
  if (list.loading) return
  const before = direction === 'before'
  const offset = before ? Math.max(0, list.start - PAGE) : list.start + list.items.length
  const limit = before ? list.start - offset : PAGE
  if (limit <= 0 || (!before && offset >= list.total)) return

  const request = listRequest // a full reload while we wait makes this page stale
  list.loading = true
  try {
    const page = await api.listContacts({ ...currentFilters(), offset, limit })
    if (request !== listRequest) return
    if (before) {
      list.items = [...page.items, ...list.items]
      list.start = offset
    } else {
      list.items = [...list.items, ...page.items]
    }
    list.total = page.total
  } catch (e) {
    if (request === listRequest) list.error = e.message
  } finally {
    if (request === listRequest) list.loading = false
  }
}

/** Make sure the letter's first contact is loaded; the list then scrolls to it. */
async function jumpToLetter(letter) {
  const entry = list.letters.find((l) => l.letter === letter)
  if (!entry) return
  const loaded = entry.offset >= list.start && entry.offset < list.start + list.items.length
  if (!loaded) await loadList({ offset: entry.offset })
}

async function loadMeta() {
  const [t, s] = await Promise.all([api.listTags(), api.stats()])
  tags.value = t
  stats.value = s
}

async function refreshAll() {
  await Promise.all([reloadList(), loadMeta()])
}

function resetList() {
  listKey.value++
  loadList()
}

let searchTimer
watch(() => filter.q, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(resetList, 120)
})
watch(() => [filter.view, filter.tagId], resetList)

async function select(id) {
  mode.value = 'view'
  selectedId.value = id
  if (id === null) { selected.value = null; return }
  try {
    const contact = await api.getContact(id)
    if (selectedId.value === id) selected.value = contact
  } catch (e) {
    notify(e.message, 'error')
  }
}

function startNew() {
  selectedId.value = null
  selected.value = null
  mode.value = 'new'
}

function closeDetail() {
  if (mode.value === 'edit') { mode.value = 'view'; return }
  mode.value = 'view'
  selectedId.value = null
  selected.value = null
}

async function save(input) {
  const creating = mode.value === 'new'
  const contact = creating
    ? await api.createContact(input)
    : await api.updateContact(selected.value.id, input)
  selected.value = contact
  selectedId.value = contact.id
  mode.value = 'view'
  notify(creating ? `Added ${displayName(contact)}` : 'Changes saved')
  refreshAll()
}

async function remove(contact) {
  if (!confirm(`Delete ${displayName(contact)}? This can't be undone.`)) return
  try {
    await api.deleteContact(contact.id)
    notify(`Deleted ${displayName(contact)}`)
    closeDetail()
    refreshAll()
  } catch (e) {
    notify(e.message, 'error')
  }
}

async function toggleFavorite(contact) {
  const favorite = !contact.favorite
  try {
    await api.setFavorite(contact.id, favorite)
    if (selected.value?.id === contact.id) selected.value.favorite = favorite
    const row = list.items.find((c) => c.id === contact.id)
    if (row) row.favorite = favorite
    stats.value.favorites += favorite ? 1 : -1
    if (filter.view === 'favorites') reloadList()
  } catch (e) {
    notify(e.message, 'error')
  }
}

async function createTag(input) {
  try {
    await api.createTag(input)
    await loadMeta()
    return true
  } catch (e) {
    notify(e.message, 'error')
    return false
  }
}

async function deleteTag(tag) {
  const n = tag.contact_count
  const note = n ? ` It will be removed from ${n} contact${n === 1 ? '' : 's'}.` : ''
  if (!confirm(`Delete the "${tag.name}" tag?${note}`)) return
  try {
    await api.deleteTag(tag.id)
    if (filter.view === 'tag' && filter.tagId === tag.id) {
      filter.view = 'all'
      filter.tagId = null
    }
    if (selected.value) select(selected.value.id)
    await refreshAll()
  } catch (e) {
    notify(e.message, 'error')
  }
}

function setView(view, tagId = null) {
  filter.view = view
  filter.tagId = tagId
}

onMounted(() => Promise.all([loadList(), loadMeta()]))
</script>

<template>
  <div class="flex h-full flex-col lg:flex-row">
    <Sidebar
      :filter="filter"
      :stats="stats"
      :tags="tags"
      @set-view="setView"
      :create-tag="createTag"
      @new-contact="startNew"
      @delete-tag="deleteTag"
    />

    <!-- List and detail share a row at every width; on phones they take turns. -->
    <div class="flex min-h-0 min-w-0 flex-1">
      <ContactList
        :class="showingDetail ? 'hidden md:flex' : 'flex'"
        v-model:query="filter.q"
        :title="filterTitle"
        :items="list.items"
        :start="list.start"
        :total="list.total"
        :letters="list.letters"
        :list-key="listKey"
        :loading="list.loading"
        :error="list.error"
        :selected-id="selectedId"
        :tags-by-id="tagsById"
        :load-adjacent="loadAdjacent"
        :jump-to-letter="jumpToLetter"
        @select="select"
        @new-contact="startNew"
      />

      <main
        class="min-w-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 lg:px-12 lg:py-10"
        :class="showingDetail ? 'block' : 'hidden md:block'"
      >
        <ContactForm
          v-if="mode !== 'view'"
          :key="mode + (selected?.id ?? 'new')"
          :contact="mode === 'edit' ? selected : null"
          :tags="tags"
          :save="save"
          :create-tag="createTag"
          @cancel="closeDetail"
        />
        <ContactCard
          v-else-if="selected"
          :contact="selected"
          @edit="mode = 'edit'"
          @delete="remove"
          @toggle-favorite="toggleFavorite"
          @close="closeDetail"
          @filter-tag="(id) => setView('tag', id)"
        />
        <div v-else-if="selectedId === null" class="mx-auto mt-24 max-w-sm text-center text-graphite">
          <p class="font-display text-2xl text-ink">Pick a card</p>
          <p class="mt-2 text-sm">
            Choose someone from the list to see their details, or
            <button class="text-cobalt underline underline-offset-2" @click="startNew">add a contact</button>.
          </p>
        </div>
      </main>
    </div>

    <Transition
      enter-from-class="opacity-0 translate-y-2" leave-to-class="opacity-0"
      enter-active-class="transition duration-150" leave-active-class="transition duration-150"
    >
      <div
        v-if="toast"
        :key="toast.key"
        role="status"
        class="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-md px-4 py-2.5 text-sm shadow-lg"
        :class="toast.tone === 'error' ? 'bg-margin text-white' : 'bg-ink text-white'"
      >
        {{ toast.message }}
      </div>
    </Transition>
  </div>
</template>

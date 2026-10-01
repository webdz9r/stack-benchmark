<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ALPHABET, fileLetter, initials, tagStyle } from '../format'

const props = defineProps({
  query: String,
  title: String,
  items: Array,
  start: Number, // position of items[0] in the full sorted list
  total: Number,
  letters: Array, // [{ letter, offset, count }] for the current filters
  listKey: Number, // changes when the filters change
  loading: Boolean,
  error: String,
  selectedId: Number,
  tagsById: Object,
  loadAdjacent: Function, // async ('before' | 'after') => void
  jumpToLetter: Function, // async (letter) => void; loads the letter's rows if needed
})
const emit = defineEmits(['update:query', 'select', 'new-contact'])

const searchInput = ref(null)
const topSentinel = ref(null)
const bottomSentinel = ref(null)
const scroller = ref(null)
const activeLetter = ref(null)
const searching = computed(() => props.query.trim().length > 0)

// Group rows under index-card letter tabs. The API returns them sorted, so
// consecutive rows with the same letter form one group.
const groups = computed(() => {
  const out = []
  for (const c of props.items) {
    const letter = fileLetter(c)
    if (out.at(-1)?.letter !== letter) out.push({ letter, contacts: [] })
    out.at(-1).contacts.push(c)
  }
  return out
})
const hasEarlier = computed(() => props.start > 0)
const hasMore = computed(() => props.start + props.items.length < props.total)
const lettersByKey = computed(() => Object.fromEntries(props.letters.map((l) => [l.letter, l])))

// While jumping, ignore the sentinels so they don't fetch pages mid-scroll.
let jumping = false

async function loadEarlier() {
  // Keep the rows on screen still while earlier rows are added above them.
  const el = scroller.value
  const fromBottom = el.scrollHeight - el.scrollTop
  await props.loadAdjacent('before')
  await nextTick()
  el.scrollTop = el.scrollHeight - fromBottom
}

async function jump(letter) {
  if (!lettersByKey.value[letter]) return
  jumping = true
  try {
    await props.jumpToLetter(letter)
    await nextTick()
    const group = scroller.value.querySelector(`[data-letter="${letter}"]`)
    scroller.value.scrollTop = group ? group.offsetTop : 0
    activeLetter.value = letter
  } finally {
    jumping = false
    recheckSentinels()
  }
}

// The rail highlights the letter group at the top of the visible list.
let frame = 0
function trackActiveLetter() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    const el = scroller.value
    if (!el) return
    let current = groups.value[0]?.letter ?? null
    for (const g of el.querySelectorAll('[data-letter]')) {
      if (g.offsetTop > el.scrollTop + 1) break
      current = g.dataset.letter
    }
    activeLetter.value = current
  })
}
watch(() => props.items, () => nextTick(trackActiveLetter))
watch(() => props.listKey, () => { if (scroller.value) scroller.value.scrollTop = 0 })

let observer
function recheckSentinels() {
  // A sentinel that stays on screen won't fire again on its own; re-observing
  // forces a fresh check.
  for (const el of [topSentinel.value, bottomSentinel.value]) {
    if (!el) continue
    observer.unobserve(el)
    observer.observe(el)
  }
}

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (jumping || props.loading) return
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        if (entry.target === topSentinel.value && hasEarlier.value) loadEarlier()
        if (entry.target === bottomSentinel.value && hasMore.value) props.loadAdjacent('after')
      }
    },
    // Root is the scrolling list so the margin prefetches before either end.
    { root: scroller.value, rootMargin: '400px 0px' },
  )
  recheckSentinels()
  watch(() => props.loading, (loading) => { if (!loading) nextTick(recheckSentinels) })
  window.addEventListener('keydown', focusSearchShortcut)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(frame)
  window.removeEventListener('keydown', focusSearchShortcut)
})

// "/" focuses search from anywhere that isn't already a text field.
function focusSearchShortcut(e) {
  const typing = e.target.closest?.('input, textarea, select, [contenteditable]')
  if (e.key === '/' && !typing) {
    e.preventDefault()
    searchInput.value?.focus()
  }
}

function secondaryLine(c) {
  if (c.company && (c.first_name || c.last_name)) {
    return c.job_title ? `${c.job_title}, ${c.company}` : c.company
  }
  return c.email || c.phone || ''
}
</script>

<template>
  <section
    class="min-h-0 w-full shrink-0 flex-col border-rule bg-paper md:w-80 md:border-r lg:w-96"
    aria-label="Contacts"
  >
    <header class="border-b border-rule px-4 pt-4 pb-3">
      <div class="mb-3 flex items-baseline justify-between">
        <h2 class="text-sm font-semibold">{{ title }}</h2>
        <span class="font-mono text-xs text-graphite" aria-live="polite">
          {{ total.toLocaleString() }} {{ searching ? 'found' : total === 1 ? 'card' : 'cards' }}
        </span>
      </div>
      <label class="relative block">
        <span class="sr-only">Search contacts</span>
        <svg class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-graphite" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.45 4.39l3.08 3.08a.75.75 0 1 1-1.06 1.06l-3.08-3.08A7 7 0 0 1 2 9Z" clip-rule="evenodd" />
        </svg>
        <input
          ref="searchInput"
          type="search"
          class="input pl-9 pr-8"
          placeholder="Search names, email, phone, city…"
          :value="query"
          @input="emit('update:query', $event.target.value)"
          @keydown.esc="emit('update:query', '')"
        />
        <kbd class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded border border-rule px-1.5 font-mono text-[10px] text-graphite">/</kbd>
      </label>
    </header>

    <div class="flex min-h-0 flex-1">
      <nav
        v-if="items.length || loading"
        aria-label="Jump to letter"
        class="no-scrollbar flex w-7 shrink-0 flex-col overflow-y-auto border-r border-rule py-1.5"
      >
        <button
          v-for="letter in ALPHABET"
          :key="letter"
          type="button"
          class="rail-letter"
          :class="{ active: letter === activeLetter }"
          :disabled="!lettersByKey[letter]"
          :aria-current="letter === activeLetter ? 'true' : undefined"
          :aria-label="lettersByKey[letter]
            ? `Jump to ${letter === '#' ? 'other' : letter} (${lettersByKey[letter].count.toLocaleString()})`
            : `No contacts under ${letter === '#' ? 'other' : letter}`"
          @click="jump(letter)"
        >{{ letter }}</button>
      </nav>

      <div ref="scroller" class="relative min-h-0 flex-1 overflow-y-auto" @scroll.passive="trackActiveLetter">
        <div ref="topSentinel" class="h-px" />
        <p v-if="error" class="m-4 rounded-md bg-red-50 px-3 py-2 text-sm text-margin">
          Couldn't load contacts: {{ error }}. Check that the API is running on port 7878.
        </p>

        <div v-else-if="!loading && items.length === 0" class="px-6 py-16 text-center text-sm text-graphite">
          <template v-if="searching">
            No one matches “{{ query }}”.
            <button class="mt-2 block w-full text-cobalt hover:underline" @click="emit('update:query', '')">Clear search</button>
          </template>
          <template v-else>
            No contacts here yet.
            <button class="mt-2 block w-full text-cobalt hover:underline" @click="emit('new-contact')">Add a contact</button>
          </template>
        </div>

        <div v-for="group in groups" :key="group.letter" :data-letter="group.letter">
          <h3
            class="sticky top-0 z-10 flex items-center gap-3 bg-paper/95 px-4 py-1.5 backdrop-blur-sm"
          >
            <span class="font-display text-lg leading-none text-cobalt">{{ group.letter }}</span>
            <span class="h-px flex-1 bg-rule" aria-hidden="true" />
          </h3>
          <ul>
            <li v-for="c in group.contacts" :key="c.id">
              <button
                class="flex w-full items-center gap-3 border-l-2 px-4 py-2.5 text-left transition-colors"
                :class="c.id === selectedId
                  ? 'border-cobalt bg-card'
                  : 'border-transparent hover:bg-card/60'"
                :aria-current="c.id === selectedId ? 'true' : undefined"
                @click="emit('select', c.id)"
              >
                <span
                  class="grid size-9 shrink-0 place-items-center rounded-full bg-card font-mono text-xs font-medium text-graphite ring-1 ring-rule"
                  aria-hidden="true"
                >{{ initials(c) }}</span>
                <span class="min-w-0 flex-1">
                  <span class="flex items-center gap-1.5">
                    <span class="truncate text-sm">
                      {{ c.first_name }} <strong class="font-semibold">{{ c.last_name }}</strong>
                      <strong v-if="!c.first_name && !c.last_name" class="font-semibold">{{ c.company }}</strong>
                    </span>
                    <svg v-if="c.favorite" class="size-3.5 shrink-0 text-amber-500" viewBox="0 0 20 20" fill="currentColor" aria-label="Favorite">
                      <path d="M10 1.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L10 14.9l-5.25 2.7 1-5.8L1.5 7.7l5.9-.9L10 1.5z" />
                    </svg>
                  </span>
                  <span class="flex items-center gap-2">
                    <span class="truncate text-xs text-graphite">{{ secondaryLine(c) }}</span>
                    <span class="ml-auto flex shrink-0 gap-1" aria-hidden="true">
                      <span
                        v-for="id in c.tag_ids" :key="id"
                        class="size-1.5 rounded-full" :class="tagStyle(tagsById[id]?.color).dot"
                        :title="tagsById[id]?.name"
                      />
                    </span>
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </div>

        <div ref="bottomSentinel" class="h-px" />
        <p v-if="loading" class="py-4 text-center font-mono text-xs text-graphite">Loading…</p>
        <p v-else-if="items.length && !hasMore && items.length > 12" class="py-6 text-center font-mono text-xs text-graphite">
          End of the file · {{ total.toLocaleString() }} {{ total === 1 ? 'card' : 'cards' }}
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
@reference "../style.css";

.no-scrollbar { scrollbar-width: none; }

.rail-letter {
  @apply mx-auto grid min-h-3.5 w-5 flex-1 place-items-center rounded font-mono text-[10.5px] leading-none
         text-graphite transition-colors hover:bg-cobalt-soft hover:text-cobalt;
}
.rail-letter.active {
  @apply bg-cobalt font-medium text-white hover:bg-cobalt hover:text-white;
}
.rail-letter:disabled {
  @apply cursor-default text-rule hover:bg-transparent hover:text-rule;
}
</style>

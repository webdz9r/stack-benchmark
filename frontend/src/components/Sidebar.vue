<script setup>
import { ref } from 'vue'
import { TAG_COLORS, tagStyle } from '../format'

const props = defineProps({
  filter: Object,
  stats: Object,
  tags: Array,
  createTag: Function, // async (input) => boolean
})
const emit = defineEmits(['set-view', 'new-contact', 'delete-tag'])

const adding = ref(false)
const newName = ref('')
const newColor = ref('sky')

async function submitTag() {
  const name = newName.value.trim()
  if (!name) return
  // The parent reports failures; only reset the form on success.
  if (await props.createTag({ name, color: newColor.value })) {
    newName.value = ''
    adding.value = false
  }
}

const isActive = (view, tagId = null) =>
  props.filter.view === view && (view !== 'tag' || props.filter.tagId === tagId)
const count = (n) => n.toLocaleString()
</script>

<template>
  <aside
    class="flex shrink-0 flex-col gap-4 border-rule bg-card px-4 py-4
           lg:w-60 lg:gap-6 lg:border-r lg:px-5 lg:py-7"
  >
    <div class="flex items-center justify-between gap-3">
      <h1 class="font-display text-xl leading-none tracking-tight lg:text-2xl">Address Book</h1>
      <button class="btn btn-primary lg:hidden" @click="emit('new-contact')">New contact</button>
    </div>

    <button class="btn btn-primary hidden justify-center lg:inline-flex" @click="emit('new-contact')">
      New contact
    </button>

    <nav aria-label="Filters" class="no-scrollbar -mx-4 overflow-x-auto px-4 lg:mx-0 lg:overflow-visible lg:px-0">
      <ul class="flex gap-1 lg:flex-col">
        <li>
          <button
            class="nav-item" :class="{ active: isActive('all') }"
            :aria-current="isActive('all') ? 'page' : undefined"
            @click="emit('set-view', 'all')"
          >
            <span>All contacts</span><span class="count">{{ count(stats.contacts) }}</span>
          </button>
        </li>
        <li>
          <button
            class="nav-item" :class="{ active: isActive('favorites') }"
            :aria-current="isActive('favorites') ? 'page' : undefined"
            @click="emit('set-view', 'favorites')"
          >
            <span>Favorites</span><span class="count">{{ count(stats.favorites) }}</span>
          </button>
        </li>

        <li class="field-label hidden px-2.5 pt-5 pb-1.5 lg:block">Tags</li>

        <li v-for="tag in tags" :key="tag.id" class="group relative">
          <button
            class="nav-item" :class="{ active: isActive('tag', tag.id) }"
            :aria-current="isActive('tag', tag.id) ? 'page' : undefined"
            @click="emit('set-view', 'tag', tag.id)"
          >
            <span class="flex items-center gap-2">
              <span class="size-2 rounded-full" :class="tagStyle(tag.color).dot" />
              {{ tag.name }}
            </span>
            <span class="count lg:group-hover:invisible lg:group-focus-within:invisible">
              {{ count(tag.contact_count) }}
            </span>
          </button>
          <button
            class="absolute top-1/2 right-1.5 hidden -translate-y-1/2 rounded px-1.5 py-0.5 text-xs text-graphite
                   hover:bg-red-50 hover:text-margin lg:group-hover:block lg:group-focus-within:block"
            :aria-label="`Delete tag ${tag.name}`"
            @click="emit('delete-tag', tag)"
          >
            Delete
          </button>
        </li>
      </ul>
    </nav>

    <div class="hidden lg:block">
      <form v-if="adding" class="space-y-2" @submit.prevent="submitTag">
        <input
          v-model="newName" class="input" placeholder="Tag name" maxlength="40"
          aria-label="New tag name" autofocus @keydown.esc="adding = false"
        />
        <div class="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Tag color">
          <button
            v-for="c in TAG_COLORS" :key="c" type="button" role="radio"
            :aria-checked="newColor === c" :aria-label="c"
            class="size-5 rounded-full ring-offset-2 transition"
            :class="[tagStyle(c).dot, newColor === c ? 'ring-2 ring-ink' : 'opacity-60 hover:opacity-100']"
            @click="newColor = c"
          />
        </div>
        <div class="flex gap-1">
          <button class="btn btn-primary px-3 py-1.5" type="submit">Add tag</button>
          <button class="btn btn-quiet px-3 py-1.5" type="button" @click="adding = false">Cancel</button>
        </div>
      </form>
      <button v-else class="px-2.5 text-sm text-cobalt hover:underline" @click="adding = true">
        + New tag
      </button>
    </div>
  </aside>
</template>

<style scoped>
@reference "../style.css";

.nav-item {
  @apply flex w-full items-center justify-between gap-4 whitespace-nowrap rounded-md px-2.5 py-1.5
         text-left text-sm text-ink transition-colors hover:bg-paper;
}
.nav-item.active {
  @apply bg-cobalt-soft font-medium text-cobalt;
}
.no-scrollbar { scrollbar-width: none; }
.count {
  @apply font-mono text-xs text-graphite;
}
</style>

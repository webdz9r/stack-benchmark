<script setup>
import { computed } from 'vue'
import { displayName, formatAddress, formatBirthday, initials, mapsUrl, tagStyle } from '../format'

const props = defineProps({ contact: Object })
const emit = defineEmits(['edit', 'delete', 'toggle-favorite', 'close', 'filter-tag'])

const c = computed(() => props.contact)
const subtitle = computed(() => {
  const hasName = c.value.first_name || c.value.last_name
  return [c.value.job_title, hasName ? c.value.company : ''].filter(Boolean).join(' · ')
})
const telHref = (v) => `tel:${v.replace(/[^\d+]/g, '')}`
const updated = computed(() =>
  new Date(c.value.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }),
)
</script>

<template>
  <article class="mx-auto max-w-2xl">
    <div class="mb-4 flex items-center justify-between gap-2">
      <button class="btn btn-quiet -ml-3 md:hidden" @click="emit('close')">← Back</button>
      <div class="ml-auto flex gap-1">
        <button
          class="btn btn-quiet"
          :aria-pressed="c.favorite"
          @click="emit('toggle-favorite', c)"
        >
          <svg class="size-4" :class="c.favorite ? 'text-amber-500' : 'text-graphite'" viewBox="0 0 20 20" :fill="c.favorite ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path d="M10 1.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L10 14.9l-5.25 2.7 1-5.8L1.5 7.7l5.9-.9L10 1.5z" />
          </svg>
          {{ c.favorite ? 'Favorited' : 'Favorite' }}
        </button>
        <button class="btn btn-quiet" @click="emit('edit')">Edit</button>
        <button class="btn btn-danger" @click="emit('delete', c)">Delete</button>
      </div>
    </div>

    <div class="index-card overflow-hidden">
      <header class="card-rule flex items-end gap-4 px-6 pt-7 pb-4 sm:px-8">
        <div
          class="grid size-14 shrink-0 place-items-center rounded-full bg-cobalt-soft font-mono text-base font-medium text-cobalt"
          aria-hidden="true"
        >{{ initials(c) }}</div>
        <div class="min-w-0">
          <h2 class="font-display text-3xl leading-tight break-words">{{ displayName(c) }}</h2>
          <p v-if="subtitle" class="mt-0.5 text-sm text-graphite">{{ subtitle }}</p>
        </div>
      </header>

      <div class="grid gap-x-8 gap-y-6 px-6 py-6 sm:grid-cols-2 sm:px-8">
        <section v-if="c.emails.length" class="sm:col-span-2">
          <h3 class="field-label mb-1.5">Email</h3>
          <ul class="space-y-1">
            <li v-for="(e, i) in c.emails" :key="i" class="flex min-w-0 items-baseline gap-3">
              <a :href="`mailto:${e.value}`" class="truncate font-mono text-[15px] text-cobalt hover:underline">{{ e.value }}</a>
              <span class="shrink-0 text-xs text-graphite">{{ e.label }}</span>
            </li>
          </ul>
        </section>

        <section v-if="c.phones.length">
          <h3 class="field-label mb-1.5">Phone</h3>
          <ul class="space-y-1">
            <li v-for="(p, i) in c.phones" :key="i" class="flex items-baseline gap-3">
              <a :href="telHref(p.value)" class="font-mono text-[15px] whitespace-nowrap text-ink hover:text-cobalt">{{ p.value }}</a>
              <span class="text-xs text-graphite">{{ p.label }}</span>
            </li>
          </ul>
        </section>

        <section v-if="c.addresses.length" class="sm:col-span-2">
          <h3 class="field-label mb-1.5">Address</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <address v-for="(a, i) in c.addresses" :key="i" class="font-mono text-[15px] leading-relaxed not-italic">
              <span class="mb-0.5 block font-sans text-xs text-graphite">{{ a.label }}</span>
              <span v-for="(line, j) in formatAddress(a)" :key="j" class="block">{{ line }}</span>
              <a :href="mapsUrl(a)" target="_blank" rel="noopener" class="font-sans text-xs text-cobalt hover:underline">Open in Maps</a>
            </address>
          </div>
        </section>

        <section v-if="c.birthday">
          <h3 class="field-label mb-1.5">Birthday</h3>
          <p class="font-mono text-[15px]">{{ formatBirthday(c.birthday) }}</p>
        </section>

        <section v-if="c.tags.length">
          <h3 class="field-label mb-1.5">Tags</h3>
          <ul class="flex flex-wrap gap-1.5">
            <li v-for="t in c.tags" :key="t.id">
              <button
                class="rounded-full px-2.5 py-0.5 text-xs font-medium hover:brightness-95"
                :class="tagStyle(t.color).chip"
                :title="`Show everyone tagged ${t.name}`"
                @click="emit('filter-tag', t.id)"
              >{{ t.name }}</button>
            </li>
          </ul>
        </section>

        <p
          v-if="!c.phones.length && !c.emails.length && !c.addresses.length && !c.birthday"
          class="text-sm text-graphite sm:col-span-2"
        >
          No contact details yet. <button class="text-cobalt hover:underline" @click="emit('edit')">Add a phone or email</button>
        </p>
      </div>

      <section v-if="c.notes" class="px-6 pb-7 sm:px-8">
        <h3 class="field-label mb-1">Notes</h3>
        <p class="ruled font-mono text-[15px] whitespace-pre-wrap">{{ c.notes }}</p>
      </section>
    </div>

    <p class="mt-3 text-right font-mono text-[11px] text-graphite">Updated {{ updated }}</p>
  </article>
</template>

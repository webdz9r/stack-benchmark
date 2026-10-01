<script setup>
import { reactive, ref } from 'vue'
import { tagStyle } from '../format'

const props = defineProps({
  contact: Object, // null when creating
  tags: Array,
  save: Function, // async (input) => void, throws on failure
  createTag: Function, // async (input) => boolean
})
const emit = defineEmits(['cancel'])

const EMAIL_LABELS = ['home', 'work', 'other']
const PHONE_LABELS = ['mobile', 'home', 'work', 'other']
const ADDRESS_LABELS = ['home', 'work', 'other']
const blankAddress = () => ({ label: 'home', street: '', city: '', region: '', postal_code: '', country: '' })

const src = props.contact
const form = reactive({
  first_name: src?.first_name ?? '',
  last_name: src?.last_name ?? '',
  company: src?.company ?? '',
  job_title: src?.job_title ?? '',
  birthday: src?.birthday ?? '',
  notes: src?.notes ?? '',
  favorite: src?.favorite ?? false,
  emails: src?.emails.map((e) => ({ ...e })) ?? [{ label: 'home', value: '' }],
  phones: src?.phones.map((p) => ({ ...p })) ?? [{ label: 'mobile', value: '' }],
  addresses: src?.addresses.map((a) => ({ ...a })) ?? [],
  tag_ids: src?.tags.map((t) => t.id) ?? [],
})

const saving = ref(false)
const error = ref('')
const newTag = ref('')

function toggleTag(id) {
  const i = form.tag_ids.indexOf(id)
  i === -1 ? form.tag_ids.push(id) : form.tag_ids.splice(i, 1)
}

async function addTag() {
  const name = newTag.value.trim()
  if (!name) return
  if (await props.createTag({ name, color: 'slate' })) {
    const tag = props.tags.find((t) => t.name.toLowerCase() === name.toLowerCase())
    if (tag && !form.tag_ids.includes(tag.id)) form.tag_ids.push(tag.id)
    newTag.value = ''
  }
}

async function submit() {
  error.value = ''
  saving.value = true
  try {
    await props.save({ ...form, birthday: form.birthday || null })
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="mx-auto max-w-2xl" novalidate @submit.prevent="submit" @keydown.esc="emit('cancel')">
    <div class="index-card overflow-hidden">
      <header class="card-rule px-6 pt-7 pb-4 sm:px-8">
        <h2 class="font-display text-3xl">{{ contact ? 'Edit contact' : 'New contact' }}</h2>
      </header>

      <div class="space-y-7 px-6 py-6 sm:px-8">
        <fieldset class="grid gap-4 sm:grid-cols-2">
          <legend class="sr-only">Name and work</legend>
          <label class="block">
            <span class="field-label">First name</span>
            <input v-model="form.first_name" class="input mt-1" autocomplete="off" autofocus />
          </label>
          <label class="block">
            <span class="field-label">Last name</span>
            <input v-model="form.last_name" class="input mt-1" autocomplete="off" />
          </label>
          <label class="block">
            <span class="field-label">Company</span>
            <input v-model="form.company" class="input mt-1" autocomplete="off" />
          </label>
          <label class="block">
            <span class="field-label">Job title</span>
            <input v-model="form.job_title" class="input mt-1" autocomplete="off" />
          </label>
        </fieldset>

        <fieldset>
          <legend class="field-label mb-2">Phone</legend>
          <div v-for="(p, i) in form.phones" :key="i" class="mb-2 flex gap-2">
            <select v-model="p.label" class="input w-28 shrink-0" aria-label="Phone label">
              <option v-for="l in PHONE_LABELS" :key="l">{{ l }}</option>
              <option v-if="!PHONE_LABELS.includes(p.label)">{{ p.label }}</option>
            </select>
            <input v-model="p.value" type="tel" class="input font-mono" placeholder="+1 555 010 0199" aria-label="Phone number" />
            <button type="button" class="remove" :aria-label="`Remove phone ${i + 1}`" @click="form.phones.splice(i, 1)">×</button>
          </div>
          <button type="button" class="add" @click="form.phones.push({ label: 'mobile', value: '' })">+ Add phone</button>
        </fieldset>

        <fieldset>
          <legend class="field-label mb-2">Email</legend>
          <div v-for="(e, i) in form.emails" :key="i" class="mb-2 flex gap-2">
            <select v-model="e.label" class="input w-28 shrink-0" aria-label="Email label">
              <option v-for="l in EMAIL_LABELS" :key="l">{{ l }}</option>
              <option v-if="!EMAIL_LABELS.includes(e.label)">{{ e.label }}</option>
            </select>
            <input v-model="e.value" type="email" class="input font-mono" placeholder="name@example.com" aria-label="Email address" />
            <button type="button" class="remove" :aria-label="`Remove email ${i + 1}`" @click="form.emails.splice(i, 1)">×</button>
          </div>
          <button type="button" class="add" @click="form.emails.push({ label: 'home', value: '' })">+ Add email</button>
        </fieldset>

        <fieldset>
          <legend class="field-label mb-2">Address</legend>
          <div v-for="(a, i) in form.addresses" :key="i" class="mb-3 rounded-md border border-rule p-3">
            <div class="mb-2 flex items-center justify-between gap-2">
              <select v-model="a.label" class="input w-28" aria-label="Address label">
                <option v-for="l in ADDRESS_LABELS" :key="l">{{ l }}</option>
                <option v-if="!ADDRESS_LABELS.includes(a.label)">{{ a.label }}</option>
              </select>
              <button type="button" class="remove" :aria-label="`Remove address ${i + 1}`" @click="form.addresses.splice(i, 1)">×</button>
            </div>
            <div class="grid gap-2 sm:grid-cols-6">
              <input v-model="a.street" class="input sm:col-span-6" placeholder="Street" aria-label="Street" />
              <input v-model="a.city" class="input sm:col-span-3" placeholder="City" aria-label="City" />
              <input v-model="a.region" class="input sm:col-span-1" placeholder="State" aria-label="State or region" />
              <input v-model="a.postal_code" class="input sm:col-span-2" placeholder="Postal code" aria-label="Postal code" />
              <input v-model="a.country" class="input sm:col-span-6" placeholder="Country" aria-label="Country" />
            </div>
          </div>
          <button type="button" class="add" @click="form.addresses.push(blankAddress())">+ Add address</button>
        </fieldset>

        <fieldset class="grid gap-4 sm:grid-cols-2">
          <legend class="sr-only">Other details</legend>
          <label class="block">
            <span class="field-label">Birthday</span>
            <input v-model="form.birthday" type="date" class="input mt-1" />
          </label>
          <label class="flex items-center gap-2 self-end pb-2 text-sm">
            <input v-model="form.favorite" type="checkbox" class="size-4 accent-cobalt" />
            Add to favorites
          </label>
        </fieldset>

        <fieldset>
          <legend class="field-label mb-2">Tags</legend>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="t in tags" :key="t.id" type="button"
              class="rounded-full px-2.5 py-1 text-xs font-medium transition"
              :class="form.tag_ids.includes(t.id)
                ? tagStyle(t.color).chip + ' ring-1 ring-current'
                : 'bg-paper text-graphite hover:text-ink'"
              :aria-pressed="form.tag_ids.includes(t.id)"
              @click="toggleTag(t.id)"
            >{{ t.name }}</button>
            <input
              v-model="newTag" class="input w-32 py-1 text-xs" placeholder="New tag…" maxlength="40"
              aria-label="Create a tag" @keydown.enter.prevent="addTag"
            />
          </div>
        </fieldset>

        <label class="block">
          <span class="field-label">Notes</span>
          <textarea v-model="form.notes" rows="4" class="input ruled mt-1 font-mono" />
        </label>
      </div>
    </div>

    <p v-if="error" role="alert" class="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-margin">{{ error }}</p>

    <div class="mt-4 flex justify-end gap-2">
      <button type="button" class="btn btn-quiet" @click="emit('cancel')">Cancel</button>
      <button type="submit" class="btn btn-primary" :disabled="saving">
        {{ saving ? 'Saving…' : contact ? 'Save changes' : 'Add contact' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
@reference "../style.css";

.remove {
  @apply grid size-9 shrink-0 place-items-center rounded-md text-lg text-graphite hover:bg-red-50 hover:text-margin;
}
.add {
  @apply text-sm text-cobalt hover:underline;
}
</style>

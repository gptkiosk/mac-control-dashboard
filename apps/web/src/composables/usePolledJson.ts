import { ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { ApiError, getJson } from '@/lib/api'
import { usePoll } from './usePoll'

/**
 * Poll a JSON endpoint. `pending` is true while the API answers 503 (it has
 * nothing to report yet); `error` holds any other failure while the last good
 * `data` stays on screen. Changing `path` clears the data and refetches.
 */
export function usePolledJson<T>(path: MaybeRefOrGetter<string>, intervalMs: MaybeRefOrGetter<number>) {
  const data = shallowRef<T | null>(null)
  const error = ref<string | null>(null)
  const pending = ref(false)
  const loaded = ref(false)
  let seq = 0

  async function load(): Promise<void> {
    const mine = ++seq
    try {
      const result = await getJson<T>(toValue(path))
      if (mine !== seq) return
      data.value = result
      error.value = null
      pending.value = false
    } catch (e) {
      if (mine !== seq) return
      if (e instanceof ApiError && e.status === 503) {
        pending.value = true
        error.value = null
      } else {
        pending.value = false
        error.value = e instanceof Error ? e.message : String(e)
      }
    } finally {
      if (mine === seq) loaded.value = true
    }
  }

  const poll = usePoll(load, intervalMs)

  watch(
    () => toValue(path),
    () => {
      data.value = null
      error.value = null
      pending.value = false
      loaded.value = false
      poll.refresh()
    },
  )

  return { data, error, pending, loaded, refresh: poll.refresh }
}

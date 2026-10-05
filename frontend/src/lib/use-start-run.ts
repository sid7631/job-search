import { toast } from 'sonner'

import { useRunNow } from '@/lib/queries'

export function useStartRun() {
  const runNow = useRunNow()
  function start() {
    runNow.mutate(undefined, {
      onSuccess: (res) =>
        toast.success(`Run #${res.run_id} started`, {
          description: 'A browser window opens while job sites are scraped.',
        }),
      onError: (e) => toast.error('Could not start run', { description: (e as Error).message }),
    })
  }
  return { start, pending: runNow.isPending }
}

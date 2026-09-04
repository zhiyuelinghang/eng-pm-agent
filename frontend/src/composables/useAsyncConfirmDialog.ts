import { useDialog, type DialogOptions, type DialogReactive } from 'naive-ui'

type AsyncConfirmDialogOptions = Pick<
  DialogOptions,
  'title' | 'content' | 'positiveText' | 'negativeText' | 'positiveButtonProps'
> & {
  loadingText?: string
  onConfirm: () => Promise<boolean | void>
  onError?: (error: unknown) => void
}

/**
 * Keep destructive confirmations visibly pending until their request settles.
 * The action button spins, every exit is locked, and repeated clicks are
 * ignored. Returning false keeps the dialog open so the user can retry.
 */
export function useAsyncConfirmDialog() {
  const dialog = useDialog()

  function confirmAsyncAction(options: AsyncConfirmDialogOptions): DialogReactive {
    const idlePositiveText = options.positiveText || '确认'
    const idleNegativeButtonProps = {}
    let submitting = false
    let instance: DialogReactive

    instance = dialog.warning({
      title: options.title,
      content: options.content,
      positiveText: idlePositiveText,
      negativeText: options.negativeText || '取消',
      positiveButtonProps: { type: 'error', ...options.positiveButtonProps },
      negativeButtonProps: idleNegativeButtonProps,
      maskClosable: false,
      closeOnEsc: false,
      closable: false,
      onPositiveClick: async () => {
        if (submitting) return false
        submitting = true
        instance.loading = true
        instance.positiveText = options.loadingText || '正在处理…'
        instance.negativeButtonProps = { disabled: true }
        try {
          const result = await options.onConfirm()
          return result !== false
        } catch (error) {
          options.onError?.(error)
          return false
        } finally {
          submitting = false
          instance.loading = false
          instance.positiveText = idlePositiveText
          instance.negativeButtonProps = idleNegativeButtonProps
        }
      },
    })

    return instance
  }

  return { confirmAsyncAction }
}

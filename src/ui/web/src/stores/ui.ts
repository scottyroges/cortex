import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ModalType = 'purge' | 'cleanup' | null

export const useUIStore = defineStore('ui', () => {
  // Modal state
  const activeModal = ref<ModalType>(null)

  // Actions
  function openModal(modal: ModalType) {
    activeModal.value = modal
  }

  function closeModal() {
    activeModal.value = null
  }

  function openPurgeModal() {
    activeModal.value = 'purge'
  }

  function openCleanupModal() {
    activeModal.value = 'cleanup'
  }

  return {
    activeModal,
    openModal,
    closeModal,
    openPurgeModal,
    openCleanupModal,
  }
})

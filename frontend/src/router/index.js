import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/upload',
  },
  {
    path: '/upload',
    name: 'Upload',
    component: () => import('../views/UploadView.vue'),
  },
  {
    path: '/library',
    name: 'Library',
    component: () => import('../views/LibraryView.vue'),
  },
  {
    path: '/basket',
    name: 'Basket',
    component: () => import('../views/BasketView.vue'),
  },
  {
    path: '/practices',
    name: 'Practices',
    component: () => import('../views/PracticeListView.vue'),
  },
  {
    path: '/practice/editor',
    name: 'PracticeEditor',
    component: () => import('../views/PracticeEditorView.vue'),
  },
  {
    path: '/tags',
    name: 'Tags',
    component: () => import('../views/TagsView.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/SettingsView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router

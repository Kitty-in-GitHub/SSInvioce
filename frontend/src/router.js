import { createRouter, createWebHistory } from 'vue-router'
import EntryList from './views/EntryList.vue'
import EntryDetail from './views/EntryDetail.vue'
import Inbox from './views/Inbox.vue'
import Help from './views/Help.vue'
import Ledger from './views/Ledger.vue'
import Settings from './views/Settings.vue'

const routes = [
  { path: '/', name: 'home', component: EntryList },
  { path: '/entries/:id', name: 'entry', component: EntryDetail, props: true },
  { path: '/inbox', name: 'inbox', component: Inbox },
  { path: '/ledger', name: 'ledger', component: Ledger },
  { path: '/help', name: 'help', component: Help },
  { path: '/settings', name: 'settings', component: Settings },
  { path: '/upload', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})

export const pageSlugs = {
  Home: 'home', Activities: 'activities', Calendar: 'calendar', Exams: 'exams',
  'Screen Time': 'screen-time', 'AI Agent': 'ai-agent', 'AI Settings': 'ai-settings',
}

export function pageFromUrl(url) {
  const page = Object.keys(pageSlugs).find(name => pageSlugs[name] === url.searchParams.get('page'))
  return page || (url.searchParams.has('chat') ? 'AI Agent' : 'Home')
}

export function urlForPage(url, page) {
  const next = new URL(url)
  next.searchParams.set('page', pageSlugs[page] || 'home')
  if (page !== 'AI Agent') next.searchParams.delete('chat')
  return next
}

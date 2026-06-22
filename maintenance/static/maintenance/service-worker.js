/**
 * Service Worker — Painel de Manutenção (PWA)
 * ============================================
 * Estratégia:
 *   - Arquivos estáticos de CDN (Bootstrap, Chart.js, Fonts): cache-first
 *   - Páginas dinâmicas do Django: network-first (sempre busca do servidor)
 *   - Se o SW falhar ou estiver offline, a aplicação continua funcionando
 *     normalmente no modelo web tradicional de requisições.
 */

const CACHE_NAME = 'manutencao-cache-v1';

// Lista de recursos estáticos essenciais para cache
const STATIC_ASSETS = [
    // Bootstrap 5 CSS
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
    // Bootstrap Icons
    'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
    // Bootstrap 5 Bundle JS
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
    // Google Fonts - Inter
    'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap',
];

// ── INSTALL: Faz cache dos estáticos essenciais ──
self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function (cache) {
                // Usa addAll com tratamento de erros individual
                // para que uma falha em um recurso não impeça os demais
                return Promise.allSettled(
                    STATIC_ASSETS.map(function (url) {
                        return cache.add(url).catch(function (err) {
                            console.warn('[SW] Falha ao cachear:', url, err);
                        });
                    })
                );
            })
            .then(function () {
                // Ativa imediatamente sem esperar outras abas
                return self.skipWaiting();
            })
    );
});

// ── ACTIVATE: Limpa caches antigos ──
self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (cacheNames) {
            return Promise.all(
                cacheNames
                    .filter(function (name) { return name !== CACHE_NAME; })
                    .map(function (name) { return caches.delete(name); })
            );
        }).then(function () {
            // Assume controle de todas as abas abertas
            return self.clients.claim();
        })
    );
});

// ── FETCH: Estratégia híbrida ──
self.addEventListener('fetch', function (event) {
    var request = event.request;

    // Ignora requisições que não são GET (POST de formulários, CSRF, etc.)
    if (request.method !== 'GET') {
        return;
    }

    // Ignora requisições para o Django Admin e media uploads
    var url = new URL(request.url);
    if (url.pathname.startsWith('/admin/') || url.pathname.startsWith('/media/')) {
        return;
    }

    // Para recursos de CDN (fonts, Bootstrap, Chart.js): cache-first
    var isCDN = request.url.indexOf('cdn.jsdelivr.net') !== -1
             || request.url.indexOf('fonts.googleapis.com') !== -1
             || request.url.indexOf('fonts.gstatic.com') !== -1
             || request.url.indexOf('cdnjs.cloudflare.com') !== -1;

    if (isCDN) {
        event.respondWith(
            caches.match(request).then(function (cached) {
                if (cached) {
                    return cached;
                }
                return fetch(request).then(function (response) {
                    // Armazena no cache para uso futuro
                    if (response.ok) {
                        var responseClone = response.clone();
                        caches.open(CACHE_NAME).then(function (cache) {
                            cache.put(request, responseClone);
                        });
                    }
                    return response;
                });
            })
        );
        return;
    }

    // Para páginas dinâmicas do Django: network-first
    event.respondWith(
        fetch(request)
            .then(function (response) {
                return response;
            })
            .catch(function () {
                // Se a rede falhar, tenta servir do cache
                return caches.match(request);
            })
    );
});

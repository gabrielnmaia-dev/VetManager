"""
Headers de cache para a API.

Os dados do VetManager são operacionais (agenda, pets, tutores, prontuários) e
mudam a todo momento. Nenhuma resposta de /api/ deve ser guardada por
navegador, proxy ou service worker. O service worker do PWA já usa NetworkOnly
para /api/, mas o header garante o mesmo comportamento em qualquer cliente.
"""


class ApiNoStoreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
        return response

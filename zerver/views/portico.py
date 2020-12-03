from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse

from zerver.context_processors import get_realm_from_request
from zerver.decorator import add_google_analytics
from zerver.models import Realm

def pricing_view(request: HttpRequest) -> HttpResponse:
    realm = get_realm_from_request(request)
    realm_plan_type = 0
    sponsorship_pending = False

    if realm is not None:
        realm_plan_type = realm.plan_type
        if realm.plan_type == Realm.SELF_HOSTED and settings.PRODUCTION:
            return HttpResponseRedirect(settings.LANDING_PAGE_URL + "/pricing")
        if not request.user.is_authenticated:
            return redirect_to_login(next="pricing")
        if request.user.is_guest:
            return TemplateResponse(request, "404.html", status=404)
        if settings.CORPORATE_ENABLED:
            from corporate.models import get_customer_by_realm
            customer = get_customer_by_realm(realm)
            if customer is not None:
                sponsorship_pending = customer.sponsorship_pending

    return HttpResponseRedirect(settings.LANDING_PAGE_URL + f"/pricing?realm_plan_type={realm_plan_type}&sponsorship_pending={sponsorship_pending}")

def get_isolated_page(request: HttpRequest) -> bool:
    '''Accept a GET param `?nav=no` to render an isolated, navless page.'''
    return request.GET.get('nav') == 'no'

@add_google_analytics
def landing_view(request: HttpRequest, template_name: str) -> HttpResponse:
    return TemplateResponse(request, template_name)

@add_google_analytics
def terms_view(request: HttpRequest) -> HttpResponse:
    return TemplateResponse(
        request, 'zerver/terms.html',
        context={'isolated_page': get_isolated_page(request)},
    )

@add_google_analytics
def privacy_view(request: HttpRequest) -> HttpResponse:
    return TemplateResponse(
        request, 'zerver/privacy.html',
        context={'isolated_page': get_isolated_page(request)},
    )

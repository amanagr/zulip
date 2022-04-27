import render_empty_feed_notice from "../templates/empty_feed_notice.hbs";

import * as hash_util from "./hash_util";
import {page_params} from "./page_params";

export function narrow_error(narrow_banner_data) {
    const title = narrow_banner_data.title;
    const html = narrow_banner_data.html;
    const search_data = narrow_banner_data.search_data;
    const login_link = hash_util.build_login_link();

    const $empty_feed_notice = render_empty_feed_notice({
        title,
        html,
        search_data,
        login_link,
        is_spectator: page_params.is_spectator,
    });
    return $empty_feed_notice;
}

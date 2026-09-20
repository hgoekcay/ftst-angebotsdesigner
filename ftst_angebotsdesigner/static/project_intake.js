/* An explicit review applies only to the fields as they were checked. */
(function () {
    'use strict';
    const form = document.getElementById('intake-form');
    if (!form) return;
    const reviewed = form.querySelector('input[name="reviewed"]');
    if (!reviewed) return;
    function changed(event) {
        if (event.target !== reviewed) reviewed.checked = false;
    }
    form.addEventListener('input', changed);
    form.addEventListener('change', changed);
    // Browser history/form restoration must also require a fresh review.
    window.addEventListener('pageshow', function () { reviewed.checked = false; });
}());

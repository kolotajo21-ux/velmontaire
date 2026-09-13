function initCompactUX() {
  const top = document.querySelector(".top");
  const center = document.querySelector("#notification-center");

  if (top && center && !document.querySelector("#notification-toggle")) {
    let toolbar = document.querySelector(".compact-toolbar");

    if (!toolbar) {
      toolbar = document.createElement("div");
      toolbar.className = "compact-toolbar";
      const actions = document.querySelector(".top-actions") || top;
      actions.appendChild(toolbar);
    }

    const bell = document.createElement("button");
    bell.id = "notification-toggle";
    bell.className = "btn notification-toggle";
    bell.type = "button";
    bell.setAttribute("aria-label", "Notifications");
    bell.innerHTML = 'Notifications <span data-notification-badge></span>';

    toolbar.appendChild(bell);

    if (typeof loadNotifications === "function") {
      loadNotifications();
    }

    bell.addEventListener("click", () => {
      center.classList.toggle("open");
    });

    document.addEventListener("click", (event) => {
      if (
        center.classList.contains("open") &&
        !center.contains(event.target) &&
        !bell.contains(event.target)
      ) {
        center.classList.remove("open");
      }
    });
  }
}

document.addEventListener("DOMContentLoaded", initCompactUX);

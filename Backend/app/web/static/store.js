// Admin "Categories", "Delivery areas" and "Coupons": shop settings a non-technical manager looks after.
"use strict";

const store = { zones: [], categories: [], counts: {}, coupons: [] };

// A small form in the same style as the question boxes. `save` returns true to close it.
function storeDialog(title, fields, submitText, save) {
  const box = document.createElement("dialog");
  box.className = "ask product-dialog";
  box.innerHTML = `<form method="dialog" novalidate><h2>${esc(title)}</h2>${fields}
    <div class="row mt"><button type="button" class="secondary" data-no>Cancel</button><button type="submit">${esc(submitText)}</button></div></form>`;
  document.body.appendChild(box);
  $("[data-no]", box).onclick = () => box.close();
  box.addEventListener("close", () => box.remove());
  $("form", box).onsubmit = async (e) => {
    e.preventDefault();
    const button = $("button[type=submit]", box);
    button.disabled = true;
    try {
      if (await save(box)) box.close();
    } catch (err) { toast(err.message, "error"); }
    button.disabled = false;
  };
  box.showModal();
}

// ---------------------------------------------------------------- categories
async function loadCategories() {
  const [categories, items] = await Promise.all([session.api("/admin/categories"), allProducts()]);
  store.categories = categories;
  store.counts = {};
  for (const p of items) store.counts[p.category.id] = (store.counts[p.category.id] || 0) + 1;
  renderCategories();
}

function renderCategories() {
  $("#n-categories").textContent = store.categories.length;
  $("#category-list").innerHTML = store.categories.length ? store.categories.map((c) => {
    const n = store.counts[c.id] || 0;
    return `<div class="product" data-id="${esc(c.id)}">
      ${c.image_url ? `<img src="${esc(c.image_url)}" alt="" loading="lazy">` : `<div class="no-image">No photo</div>`}
      <div class="product-info"><strong>${esc(c.name)}</strong><div class="muted">${n} ${n === 1 ? "product" : "products"}</div></div>
      <div class="row tight product-actions">
        <button type="button" class="small secondary" data-edit>Edit</button>
        <button type="button" class="small danger" data-delete>Delete</button>
      </div>
    </div>`;
  }).join("") : `<p class="muted">No categories yet. Add your first one.</p>`;
}

async function uploadPhoto(file, folder) {
  const form = new FormData();
  form.append("file", file);
  return (await session.api(`/admin/uploads/images?folder=${folder}`, { method: "POST", form })).url;
}

function categoryForm(c = null) {
  storeDialog(c ? `Edit ${c.name}` : "Add a category", `
    <label for="c-name">Category name</label>
    <input id="c-name" maxlength="100" required value="${esc(c?.name || "")}" placeholder="Drinks">
    <label for="c-photo">Photo${c?.image_url ? " (choose a file only to replace it)" : ""}</label>
    <input id="c-photo" type="file" accept="image/jpeg,image/png,image/webp">`,
  c ? "Save changes" : "Add category", async (box) => {
    const name = $("#c-name", box).value.trim();
    if (name.length < 2) { toast("Enter the category name.", "error"); return false; }
    const body = { name };
    const file = $("#c-photo", box).files[0];
    if (file) body.image_url = await uploadPhoto(file, "categories");
    if (c) {
      await session.api(`/admin/categories/${c.id}`, { method: "PATCH", json: body });
    } else {
      // new categories go last in the shop's list
      body.sort_order = Math.max(0, ...store.categories.map((x) => x.sort_order || 0)) + 1;
      await session.api("/admin/categories", { method: "POST", json: body });
    }
    products.loaded = false;  // the product form lists categories too
    await loadCategories();
    toast(c ? "Saved" : `${name} is added`);
    return true;
  });
}

$("#category-add").onclick = () => categoryForm();
$("#category-list").onclick = async (e) => {
  const id = e.target.closest("[data-id]")?.dataset.id;
  const c = store.categories.find((x) => x.id === id);
  if (!c) return;
  if (e.target.closest("[data-edit]")) { categoryForm(c); return; }
  if (!e.target.closest("[data-delete]")) return;
  const n = store.counts[c.id] || 0;
  if (n) {
    toast(`${c.name} still has ${n} ${n === 1 ? "product" : "products"}. Edit them to move them to another category first.`, "error");
    return;
  }
  const yes = await ask({ title: `Delete ${c.name}?`, text: "This category will disappear from the shop.", ok: "Delete", danger: true });
  if (!yes) return;
  try {
    await session.api(`/admin/categories/${c.id}`, { method: "DELETE" });
    products.loaded = false;
    await loadCategories();
    toast(`${c.name} is deleted`);
  } catch (err) { toast(err.message, "error"); }
};

// ---------------------------------------------------------------- delivery areas
async function loadZones() {
  store.zones = await session.api("/admin/zones");
  renderZones();
}

function zoneRule(z) {
  const fee = z.delivery_fee > 0 ? `${naira(z.delivery_fee)} delivery` : "Free delivery";
  return z.free_delivery_min && z.delivery_fee > 0 ? `${fee}, free on orders of ${naira(z.free_delivery_min)} or more` : fee;
}

function renderZones() {
  $("#n-zones").textContent = store.zones.length;
  $("#zone-list").innerHTML = store.zones.length ? store.zones.map((z) => `
    <div class="product" data-id="${esc(z.id)}">
      <div class="product-info">
        <strong>${esc(z.name)}</strong>
        ${z.is_active ? "" : ` <span class="chip cancelled">Not offered</span>`}
        <div class="muted">${esc(zoneRule(z))}</div>
      </div>
      <div class="row tight product-actions"><button type="button" class="small secondary" data-edit>Edit</button></div>
    </div>`).join("") : `<p class="muted">No delivery areas yet. Customers can't check out until you add one.</p>`;
}

function zoneForm(z = null) {
  storeDialog(z ? `Edit ${z.name}` : "Add a delivery area", `
    <label for="z-name">Area name</label>
    <input id="z-name" maxlength="100" required value="${esc(z?.name || "")}" placeholder="Ikeja">
    <div class="form-pair">
      <div><label for="z-fee">Delivery fee (₦)</label><input id="z-fee" type="number" min="0" step="1" inputmode="numeric" required value="${z ? esc(z.delivery_fee) : ""}"></div>
      <div><label for="z-free">Free delivery from (₦)</label><input id="z-free" type="number" min="1" step="1" inputmode="numeric" value="${z?.free_delivery_min ? esc(z.free_delivery_min) : ""}" placeholder="Optional"></div>
    </div>
    <p class="muted">Leave "Free delivery from" empty if customers in this area always pay the fee.</p>
    <label class="check"><input id="z-active" type="checkbox" ${!z || z.is_active ? "checked" : ""}> Customers can choose this area at checkout</label>`,
  z ? "Save changes" : "Add area", async (box) => {
    const name = $("#z-name", box).value.trim();
    const feeText = $("#z-fee", box).value;
    const freeText = $("#z-free", box).value;
    const active = $("#z-active", box).checked;
    if (name.length < 2) { toast("Enter the area name.", "error"); return false; }
    if (feeText === "" || !(Number(feeText) >= 0)) { toast("Enter the delivery fee. Use 0 if delivery is free.", "error"); return false; }
    if (freeText !== "" && !(Number(freeText) > 0)) { toast("Enter an amount for free delivery, or leave it empty.", "error"); return false; }
    const othersOpen = store.zones.some((x) => x.is_active && x.id !== z?.id);
    if (!active && !othersOpen) { toast("Keep at least one area on, or customers won't be able to check out.", "error"); return false; }
    const body = { name, delivery_fee: Number(feeText), free_delivery_min: freeText === "" ? null : Number(freeText), is_active: active };
    if (z) await session.api(`/admin/zones/${z.id}`, { method: "PATCH", json: body });
    else await session.api("/admin/zones", { method: "POST", json: body });
    await loadZones();
    toast(z ? "Saved" : `${name} is added`);
    return true;
  });
}

$("#zone-add").onclick = () => zoneForm();
$("#zone-list").onclick = (e) => {
  const z = store.zones.find((x) => x.id === e.target.closest("[data-id]")?.dataset.id);
  if (z && e.target.closest("[data-edit]")) zoneForm(z);
};

// ---------------------------------------------------------------- coupons
async function loadCoupons() {
  store.coupons = await session.api("/admin/coupons");
  renderCoupons();
}

const couponExpired = (c) => c.expires_at && new Date(c.expires_at) < new Date();
const couponUsedUp = (c) => c.max_uses && c.used_count >= c.max_uses;

function couponRule(c) {
  const off = c.discount_type === "percent" ? `${Number(c.value)}% off` : `${naira(c.value)} off`;
  const min = Number(c.min_order) > 0 ? ` orders of ${naira(c.min_order)} or more` : " any order";
  const uses = c.max_uses ? `used ${c.used_count} of ${c.max_uses} times` : `used ${c.used_count} times`;
  const ends = c.expires_at ? `, ends ${new Date(c.expires_at).toLocaleDateString()}` : "";
  return `${off}${min} · ${uses}${ends}`;
}

function renderCoupons() {
  $("#n-coupons").textContent = store.coupons.length;
  $("#coupon-list").innerHTML = store.coupons.length ? store.coupons.map((c) => {
    const status = !c.is_active ? "Turned off" : couponExpired(c) ? "Ended" : couponUsedUp(c) ? "Used up" : "";
    return `<div class="product" data-id="${esc(c.id)}">
      <div class="product-info">
        <strong>${esc(c.code)}</strong>
        ${status ? ` <span class="chip cancelled">${esc(status)}</span>` : ""}
        <div class="muted">${esc(couponRule(c))}</div>
      </div>
      <div class="row tight product-actions"><button type="button" class="small secondary" data-edit>Edit</button></div>
    </div>`;
  }).join("") : `<p class="muted">No coupons yet.</p>`;
}

function couponForm(c = null) {
  const date = c?.expires_at ? new Date(c.expires_at).toISOString().slice(0, 10) : "";
  const value = c ? Number(c.value) : "";
  const min = c && Number(c.min_order) ? Number(c.min_order) : "";
  storeDialog(c ? `Edit ${c.code}` : "Add a coupon", `
    ${c ? "" : `<label for="k-code">Coupon code</label>
    <input id="k-code" maxlength="40" required placeholder="WELCOME10" style="text-transform:uppercase">
    <label for="k-type">Type of discount</label>
    <select id="k-type"><option value="percent">Percentage off, like 10%</option><option value="fixed">Amount off, like ₦500</option></select>`}
    <div class="form-pair">
      <div><label for="k-value">${c ? (c.discount_type === "percent" ? "Discount (%)" : "Amount off (₦)") : "Discount"}</label><input id="k-value" type="number" min="1" step="1" inputmode="numeric" required value="${esc(value)}"></div>
      <div><label for="k-min">Smallest order (₦)</label><input id="k-min" type="number" min="0" step="1" inputmode="numeric" value="${esc(min)}" placeholder="Any"></div>
    </div>
    <div class="form-pair">
      <div><label for="k-uses">Times it can be used</label><input id="k-uses" type="number" min="1" step="1" inputmode="numeric" value="${esc(c?.max_uses || "")}" placeholder="No limit"></div>
      <div><label for="k-date">Last day (optional)</label><input id="k-date" type="date" value="${esc(date)}"></div>
    </div>
    <label class="check"><input id="k-active" type="checkbox" ${!c || c.is_active ? "checked" : ""}> Customers can use this coupon</label>`,
  c ? "Save changes" : "Add coupon", async (box) => {
    const kind = c ? c.discount_type : $("#k-type", box).value;
    const amount = Number($("#k-value", box).value);
    const uses = $("#k-uses", box).value;
    if (!c && $("#k-code", box).value.trim().length < 3) { toast("Enter a code of at least 3 characters.", "error"); return false; }
    if (!(amount > 0)) { toast("Enter the discount.", "error"); return false; }
    if (kind === "percent" && amount > 90) { toast("A percentage coupon can be at most 90%.", "error"); return false; }
    if (uses !== "" && !(Number.isInteger(Number(uses)) && Number(uses) >= Math.max(1, c?.used_count || 0))) {
      toast(`Enter a whole number${c?.used_count ? ` of at least ${c.used_count}, the times already used` : ""}, or leave it empty.`, "error");
      return false;
    }
    const day = $("#k-date", box).value;
    const body = {
      value: amount,
      min_order: Number($("#k-min", box).value || 0),
      max_uses: uses === "" ? null : Number(uses),
      expires_at: day ? new Date(`${day}T23:59:59`).toISOString() : null,  // to the end of that day
      is_active: $("#k-active", box).checked,
    };
    if (c) {
      await session.api(`/admin/coupons/${c.id}`, { method: "PATCH", json: body });
    } else {
      await session.api("/admin/coupons", { method: "POST", json: { ...body, code: $("#k-code", box).value.trim(), discount_type: kind } });
    }
    await loadCoupons();
    toast(c ? "Saved" : "Coupon added");
    return true;
  });
}

$("#coupon-add").onclick = () => couponForm();
$("#coupon-list").onclick = (e) => {
  const c = store.coupons.find((x) => x.id === e.target.closest("[data-id]")?.dataset.id);
  if (c && e.target.closest("[data-edit]")) couponForm(c);
};

// ---------------------------------------------------------------- riders
async function loadRiders() {
  store.riders = await session.api("/admin/riders");
  renderRiders();
}

function renderRiders() {
  $("#n-riders").textContent = store.riders.length;
  $("#rider-list").innerHTML = store.riders.length ? store.riders.map((r) => {
    const extra = [r.vehicle_type, r.area].filter(Boolean).join(" · ");
    return `<div class="product" data-id="${esc(r.id)}">
      <div class="product-info">
        <strong>${esc(r.full_name)}</strong>
        ${!r.is_active ? ` <span class="chip cancelled">Suspended</span>` : r.active_deliveries ? ` <span class="chip en_route">On a delivery</span>` : ""}
        <div class="muted">${r.phone ? `<a href="tel:${esc(r.phone)}">${esc(r.phone)}</a> · ` : ""}${esc(r.email)}${extra ? ` · ${esc(extra)}` : ""}</div>
      </div>
      <div class="row tight product-actions">
        <button type="button" class="small ${r.is_active ? "danger" : "secondary"}" data-toggle-rider>${r.is_active ? "Suspend" : "Restore"}</button>
      </div>
    </div>`;
  }).join("") : `<p class="muted">No riders yet.</p>`;
}

function riderForm() {
  storeDialog("Add a rider", `
    <label for="r-name">Full name</label><input id="r-name" maxlength="150" required>
    <label for="r-phone">Phone number</label><input id="r-phone" type="tel" inputmode="tel" required placeholder="0803 123 4567">
    <label for="r-email">Email</label><input id="r-email" type="email" required>
    <label for="r-password">Temporary password</label><input id="r-password" type="text" minlength="8" autocomplete="new-password" required>
    <p class="muted">Give the rider this password yourself. They can change it with "Forgot password" on the shop's sign-in page.</p>`,
  "Add rider", async (box) => {
    const body = {
      full_name: $("#r-name", box).value.trim(), phone: $("#r-phone", box).value.trim(),
      email: $("#r-email", box).value.trim(), password: $("#r-password", box).value, role: "rider",
    };
    if (body.full_name.length < 2) { toast("Enter the rider's full name.", "error"); return false; }
    if (body.phone.replace(/\D/g, "").length < 10) { toast("Enter the rider's phone number.", "error"); return false; }
    if (!/^\S+@\S+\.\S+$/.test(body.email)) { toast("Enter a valid email.", "error"); return false; }
    if (body.password.length < 8) { toast("The password needs at least 8 characters.", "error"); return false; }
    await session.api("/admin/users", { method: "POST", json: body });
    await loadRiders();
    load().catch(() => {});  // so they appear in the "Assign rider" lists straight away
    toast(`${body.full_name} is added`);
    return true;
  });
}

$("#rider-add").onclick = () => riderForm();
$("#rider-list").onclick = async (e) => {
  const r = store.riders.find((x) => x.id === e.target.closest("[data-id]")?.dataset.id);
  if (!r || !e.target.closest("[data-toggle-rider]")) return;
  const yes = await ask(r.is_active
    ? { title: `Suspend ${r.full_name}?`, text: "They won't be able to sign in or be given deliveries until you restore them.", ok: "Suspend", danger: true }
    : { title: `Restore ${r.full_name}?`, text: "They'll be able to sign in and take deliveries again.", ok: "Restore" });
  if (!yes) return;
  try {
    await session.api(`/admin/users/${r.id}`, { method: "PATCH", json: { is_active: !r.is_active } });
    await loadRiders();
    load().catch(() => {});
    toast(r.is_active ? `${r.full_name} is suspended` : `${r.full_name} is restored`);
  } catch (err) { toast(err.message, "error"); }
};

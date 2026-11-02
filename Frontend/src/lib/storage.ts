// localStorage can be missing or throw (private mode, blocked storage): never let it break a page

export function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeJSON(key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: the value just isn't remembered */
  }
}

const KEYS = {
  tokens: "cmd.tokens",
  cartSession: "cmd.cartSession",
  orders: "cmd.orders",
} as const;

export interface StoredTokens {
  access: string;
  refresh: string;
}

export const tokenStore = {
  get: () => readJSON<StoredTokens | null>(KEYS.tokens, null),
  set: (t: StoredTokens | null) => writeJSON(KEYS.tokens, t),
};

export const cartSessionStore = {
  get: () => readJSON<string | null>(KEYS.cartSession, null),
  set: (id: string | null) => writeJSON(KEYS.cartSession, id),
};

// Guests prove access to an order with its phone number; remember it (and any bank
// transfer details) for orders placed in this browser
export interface OrderAccess {
  phone: string;
  instructions?: import("./types").TransferInstructions | null;
}

export const orderAccessStore = {
  get(orderNumber: string): OrderAccess | null {
    return readJSON<Record<string, OrderAccess>>(KEYS.orders, {})[orderNumber] ?? null;
  },
  set(orderNumber: string, access: OrderAccess): void {
    const all = readJSON<Record<string, OrderAccess>>(KEYS.orders, {});
    all[orderNumber] = { ...all[orderNumber], ...access };
    writeJSON(KEYS.orders, all);
  },
};

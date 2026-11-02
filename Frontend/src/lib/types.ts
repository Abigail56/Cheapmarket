// Shapes returned by the Cheapmarketdeal API (see Backend/app/schemas)

export type UUID = string;

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface CategoryBrief {
  id: UUID;
  name: string;
  slug: string;
}

export interface Category extends CategoryBrief {
  parent_id: UUID | null;
  image_url: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface Product {
  id: UUID;
  name: string;
  slug: string;
  description: string | null;
  unit: string;
  price: number;
  compare_at_price: number | null;
  image_url: string | null;
  is_featured: boolean;
  category: CategoryBrief;
  in_stock: boolean;
  discount_percent: number | null;
}

export type ProductSort = "newest" | "price_asc" | "price_desc" | "name";

export interface Zone {
  id: UUID;
  name: string;
  delivery_fee: number;
  free_delivery_min: number | null;
  is_active: boolean;
}

export interface CartItem {
  product: Product;
  quantity: number;
  line_total: number;
}

export interface Cart {
  session_id: string | null;
  items: CartItem[];
  item_count: number;
  subtotal: number;
  notices?: string[];
}

export interface Quote {
  subtotal: number;
  delivery_fee: number;
  discount_total: number;
  total: number;
  coupon_applied: string | null;
  free_delivery_remaining: number | null;
}

export type UserRole = "admin" | "customer" | "rider";

export interface User {
  id: UUID;
  email: string;
  phone: string | null;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  phone_verified_at: string | null;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

export interface AuthResponse extends TokenPair {
  user: User;
}

export interface Address {
  id: UUID;
  zone_id: UUID | null;
  label: string;
  street: string;
  landmark: string | null;
  city: string;
  state: string;
  phone: string | null;
  is_default: boolean;
}

export type AddressInput = Omit<Address, "id">;

export type OrderStatus =
  | "pending"
  | "confirmed"
  | "packed"
  | "out_for_delivery"
  | "delivered"
  | "cancelled";

export type PaymentMethod = "cod" | "card" | "transfer";
export type PaymentStatus = "unpaid" | "paid" | "failed" | "refunded";

export interface OrderItem {
  product_id: UUID | null;
  product_name: string;
  unit_price: number;
  quantity: number;
  line_total: number;
}

export interface Order {
  id: UUID;
  order_number: string;
  tracking_token: string;
  customer_name: string;
  customer_phone: string;
  customer_email: string | null;
  delivery_address: string;
  status: OrderStatus;
  payment_method: PaymentMethod;
  payment_status: PaymentStatus;
  subtotal: number;
  delivery_fee: number;
  discount_total: number;
  total: number;
  notes: string | null;
  created_at: string;
  items: OrderItem[];
}

export interface TransferInstructions {
  bank_name: string | null;
  account_number: string | null;
  account_name: string | null;
  amount: number;
  payment_reference: string;
  note: string;
}

export interface CheckoutResponse {
  order: Order;
  payment_instructions: TransferInstructions | null;
  next_step: "pay_online" | "pay_on_delivery" | "bank_transfer";
}

export interface PaymentInit {
  authorization_url: string;
  reference: string;
  mock?: boolean;
}

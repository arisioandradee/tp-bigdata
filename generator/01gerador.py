import json
import time
import random
import uuid
from datetime import datetime, timezone
import os

CATEGORIES_PRODUCTS = {
    "Eletrônicos": [
        {"id": 101, "name": "Smartphone Galaxy", "price": 2500.00},
        {"id": 102, "name": "Notebook Gamer", "price": 5500.00},
        {"id": 103, "name": "Fone de Ouvido Bluetooth", "price": 299.90},
        {"id": 104, "name": "Smartwatch Fit", "price": 499.00}
    ],
    "Eletrodomésticos": [
        {"id": 201, "name": "Geladeira Frost Free", "price": 3800.00},
        {"id": 202, "name": "Micro-ondas 30L", "price": 650.00},
        {"id": 203, "name": "Fritadeira Elétrica Airfryer", "price": 399.90}
    ],
    "Vestuário": [
        {"id": 301, "name": "Camiseta Algodão", "price": 59.90},
        {"id": 302, "name": "Calça Jeans Slim", "price": 149.90},
        {"id": 303, "name": "Tênis Esportivo", "price": 299.00}
    ]
}

ACTIONS = ["click", "add_to_cart", "checkout", "delivery_status_update"]
DELIVERY_STATUSES = ["order_placed", "in_transit", "out_for_delivery", "delivered"]

LOG_DIR = os.environ.get(
    "LOG_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
)
LOG_FILE = os.path.join(LOG_DIR, "ecommerce_events.log")

os.makedirs(LOG_DIR, exist_ok=True)

def generate_event():
    category = random.choice(list(CATEGORIES_PRODUCTS.keys()))
    product = random.choice(CATEGORIES_PRODUCTS[category])
    action = random.choices(ACTIONS, weights=[0.6, 0.25, 0.1, 0.05])[0]
    
    now = datetime.now(timezone.utc)
    if random.random() < 0.05:
        delay_seconds = random.randint(5, 30)
        timestamp_str = datetime.fromtimestamp(now.timestamp() - delay_seconds, tz=timezone.utc).isoformat()
    else:
        timestamp_str = now.isoformat()

    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": timestamp_str,
        "user_id": random.randint(1000, 1050),
        "product_id": product["id"],
        "product_name": product["name"],
        "category": category,
        "action": action,
        "price": product["price"],
        "delivery_status": random.choice(DELIVERY_STATUSES) if action == "delivery_status_update" else None
    }
    return event

def main():
    print(f"[Gerador] Iniciando geração contínua de eventos de e-commerce...")
    print(f"[Gerador] Gravando em: {os.path.abspath(LOG_FILE)}")
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        while True:
            event = generate_event()
            json_line = json.dumps(event, ensure_ascii=False)
            f.write(json_line + "\n")
            f.flush()
            print(f"-> {json_line}")
            time.sleep(random.uniform(0.2, 1.0))

if __name__ == "__main__":
    main()

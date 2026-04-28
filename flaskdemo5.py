from flask import Flask, redirect, render_template, request, session, jsonify # type: ignore
import psycopg2 # type: ignore
from datetime import datetime, timezone
import json

app = Flask(__name__)

# Database configuration
DB_CONFIG = {
    "host": "localhost",
    "database": "coffee_shop",
    "user": "mit",
    "password": "",
    "port": "5433"
}

def get_db_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("Database connection established successfully")
        return conn
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")
        raise

def execute_query(sql_query, params=None, fetch_type=None):
    """
    Execute a database query with proper error handling.
    
    Args:
        sql_query (str): The SQL query to execute
        params (tuple/list, optional): Query parameters
        fetch_type (str, optional): Type of fetch operation ('one', 'all', or None for actions)
    
    Returns:
        Depends on fetch_type:
        - 'one': Returns a single row or ()
        - 'all': Returns all rows or []
        - None: Returns affected row count or -1 on error
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        print(f"Executing SQL: {sql_query}")
        if params:
            print(f"With parameters: {params}")
        
        cursor.execute(sql_query, params)
        
        if fetch_type == 'one':
            result = cursor.fetchone()
            print(f"Query returned one row: {result}")
            return result if result else ()
        elif fetch_type == 'all':
            result = cursor.fetchall()
            row_count = len(result) if result else 0
            print(f"Query returned {row_count} rows")
            return result if result else []
        else:  # Action query (insert, update, delete)
            conn.commit()
            print(f"Action query affected {cursor.rowcount} rows")
            return cursor.rowcount
    except Exception as err:
        print(f"Database error: {err}")
        import traceback
        print(traceback.format_exc())
        if fetch_type is None:  # Only rollback for action queries
            if conn:
                conn.rollback()
                print("Transaction rolled back")
            return -1
        return () if fetch_type == 'one' else []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# The first entry page to the web app. Index
@app.route("/")
def index():
    # Render the dashboard if the user aldready logged in.
    if "ssn" in session and "role" in session:
        return redirect("/dashboard")
    return render_template("index.html") # otherwise the user needs to login.

# this is performed when the user clicks on the login button in index.html (index page)
@app.route("/login", methods=["POST"])
def login():
    #Handle user login. retrieve the ssn, role and password from the login in form from index webpage
    ssn = request.form.get("ssn")
    role = request.form.get("role")
    password = request.form.get("password")
    
    # if either of ssn, role or password is empty, send an error message. They are required fields.
    if not ssn:
        return render_template("error.html", message="Missing SSN")
    elif not role:
        return render_template("error.html", message="Missing role")
    elif not password:
        return render_template("error.html", message="Missing password")
    
    # match the ssn and role with their password.
    select_emp_qry = "SELECT * FROM EmployeeTable WHERE ssn = %s AND role ILIKE %s and password = %s;"
    result = execute_query(select_emp_qry, [ssn, role, password], 'one')
    
    # no result means failed to get an employee with those information. Unauthorized
    if not result:
        return render_template("error.html", message=f"No such SSN with that role found.")
    
    # save the ssn, role and name as sessions(cookie)
    session["ssn"] = result[0]
    session["role"] = result[1]
    session["name"] = result[2]
    
    return redirect("/dashboard") # redirect the role-based dashboard

# the rendering of dashboard based on the role, specific details will be visible based on the set role via session
@app.route("/dashboard")
def dashboard():
    # Render the dashboard page.
    if "ssn" not in session or "role" not in session or "name" not in session:
        return redirect("/")

    # send name and role to the dashboard webpage.
    role = session["role"]
    name = session["name"]
    return render_template("dashboard.html", role=role, name=name)

# user being able to logout from the dashboard page by submitting/clicking a button logout. Clearing the session(cookie)
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/") #redirect to login page(index)

#==================================== Making Orders by the barista ============================

# gets the preparation steps for the menu items ordered under the order_id
def get_preparation_steps(order_id):
    """
    Get preparation steps for all items in an order, including promotional items.
    
    Args:
        order_id: The ID of the order
        
    Returns:
        A list of dictionaries with preparation steps for each item.
    """
    # First, get all regular items in the order
    order_items_query = """
    SELECT m.menu_id, m.name, od.quantity
    FROM OrderDetailTable od
    JOIN MenuTable m ON od.menu_id = m.menu_id
    WHERE od.order_id = %s;
    """
    regular_items = execute_query(order_items_query, [order_id], fetch_type='all')
    
    # Then, get all promotional items in the order
    promo_items_query = """
    SELECT p.menu_id, m.name, (p.promotion_quantity * psd.quantity) as quantity, 
           p.promotion_id, p.promotion_name
    FROM PromotionSaleDetailTable psd
    JOIN PromotionTable p ON psd.promotion_id = p.promotion_id
    JOIN MenuTable m ON p.menu_id = m.menu_id
    WHERE psd.order_id = %s;
    """
    promotional_items = execute_query(promo_items_query, [order_id], fetch_type='all')
    
    # Combine all items (regular and promotional)
    all_items = []
    
    # Process regular items
    for item in regular_items:
        menu_id, name, quantity = item
        all_items.append({
            'menu_id': menu_id,
            'name': name,
            'quantity': quantity,
            'is_promotion': False
        })
    
    # Process promotional items
    for item in promotional_items:
        menu_id, name, quantity, promo_id, promo_name = item
        all_items.append({
            'menu_id': menu_id,
            'name': f"{name} (Promotion: {promo_name})",
            'quantity': quantity,
            'is_promotion': True,
            'promotion_id': promo_id
        })
    
    # Get preparation steps for all items
    preparation_steps = []
    
    for item in all_items:
        menu_id = item['menu_id']
        
        # Get recipe ID for this menu item
        recipe_query = "SELECT recipe_id FROM RecipeTable WHERE menu_id = %s;"
        recipe_result = execute_query(recipe_query, [menu_id], fetch_type='one')
        
        if not recipe_result:
            continue  # Skip if no recipe found
            
        recipe_id = recipe_result[0]
        
        # Get preparation steps
        steps_query = """
        SELECT ps.step_number, ps.description
        FROM PreparationStepsTable ps
        WHERE ps.recipe_id = %s
        ORDER BY ps.step_number;
        """
        steps = execute_query(steps_query, [recipe_id], fetch_type='all')
        
        # Get ingredients
        ingredients_query = """
        SELECT i.ingredient_name, ipt.quantity, i.unit
        FROM IngredientPreparationTable ipt
        JOIN PreparationStepsTable ps ON ipt.prep_id = ps.prep_id
        JOIN IngredientTable i ON ipt.ingredient_id = i.ingredient_id
        WHERE ps.recipe_id = %s;
        """
        ingredients = execute_query(ingredients_query, [recipe_id], fetch_type='all')
        
        # Format steps and ingredients
        formatted_steps = []
        for step in steps:
            step_number, description = step
            formatted_steps.append({
                'step_number': step_number,
                'description': description
            })
        
        formatted_ingredients = []
        for ingredient in ingredients:
            ingredient_name, quantity, unit = ingredient
            formatted_ingredients.append({
                'ingredient_name': ingredient_name,
                'quantity': quantity,
                'unit': unit
            })
        
        # Add to preparation steps
        preparation_steps.append({
            'name': item['name'],
            'quantity': item['quantity'],
            'steps': formatted_steps,
            'ingredients': formatted_ingredients
        })
    
    return preparation_steps
# Check if there are enough ingredients to fulfill the order.
# returns a list of items that cant be fulfilled due to insfuficient ingredients 
def check_ingredient_availability(order_items):
    """
    Check if there are enough ingredients to fulfill the order.
    
    Args:
        order_items: List of dicts with 'menu_id' and 'quantity' keys
    
    Returns:
        list: Names of items that cannot be fulfilled due to insufficient ingredients
    """
    
    # Get menu IDs from order
    menu_ids = [int(item["menu_id"]) for item in order_items]
    print(f"Checking ingredient availability for menu IDs: {menu_ids}")
    
    # nothing ordered
    if not menu_ids:
        return ["No menu items specified"]
    
    # Get ingredient data for these menu items
    placeholders = ', '.join(['%s'] * len(menu_ids))
    ingredients_query = f"""
    SELECT m.menu_id, m.name, ipt.ingredient_id, ing.ingredient_name, 
           ipt.quantity, ing.amount_in_stock 
    FROM menutable m 
    JOIN recipetable r ON m.menu_id = r.menu_id 
    JOIN preparationstepstable p ON r.recipe_id = p.recipe_id 
    JOIN ingredientpreparationtable ipt ON p.prep_id = ipt.prep_id 
    JOIN ingredienttable ing ON ipt.ingredient_id = ing.ingredient_id 
    WHERE m.menu_id IN ({placeholders})
    ORDER BY m.menu_id ASC;
    """
    
    ingredients_data = execute_query(ingredients_query, menu_ids, 'all')
    
    # there are no ingredients for the item ordered returned by the database
    if not ingredients_data:
        print("Warning: No ingredient data found for these menu items")
        return ["Could not find recipes for the ordered items"]
    
    # Organize data by menu_id
    menu_ingredients = {}
    for item in ingredients_data:
        menu_id = item[0]
        if menu_id not in menu_ingredients:
            menu_ingredients[menu_id] = []
        
        menu_ingredients[menu_id].append({
            'name': item[1],
            'ingredient_id': item[2],
            'ingredient_name': item[3],
            'quantity_needed': item[4],
            'stock': item[5]
        })
    
    print(f"Found ingredient data for {len(menu_ingredients)} menu items")
    
    # Track total ingredient usage across all items
    ingredient_usage = {}  # Dictionary of ingredient_id to total quantity needed
    
    # First pass: Calculate total ingredient usage
    for order_item in order_items:
        menu_id = int(order_item['menu_id'])
        quantity = int(order_item['quantity'])
        item_name = order_item.get('name', f"Menu ID {menu_id}")
        
        print(f"Calculating ingredients for {item_name} (ID: {menu_id}, Quantity: {quantity})")
        
        if menu_id not in menu_ingredients:
            # Skip this item for now, we'll add it to insufficient_items later
            continue
            
        for ingredient in menu_ingredients[menu_id]:
            ingredient_id = ingredient['ingredient_id']
            ingredient_name = ingredient['ingredient_name']
            quantity_per_item = ingredient['quantity_needed']
            total_needed = quantity_per_item * quantity
            
            print(f"  - Needs {total_needed} of {ingredient_name} (ID: {ingredient_id})")
            
            # Add to total usage for this ingredient
            if ingredient_id not in ingredient_usage:
                ingredient_usage[ingredient_id] = {
                    'total': 0, 
                    'name': ingredient_name,
                    'stock': ingredient['stock']
                }
            ingredient_usage[ingredient_id]['total'] += total_needed
    
    # Second pass: Check if any ingredients are insufficient
    insufficient_items = []
    
    for order_item in order_items:
        menu_id = int(order_item['menu_id'])
        item_name = order_item.get('name', f"Menu ID {menu_id}")
        
        # If menu item has no recipe
        if menu_id not in menu_ingredients:
            insufficient_items.append(f"{item_name} (No recipe found)")
            print(f"No recipe found for {item_name}")
            continue
        
        # Check if any ingredient used by this item is insufficient
        for ingredient in menu_ingredients[menu_id]:
            ingredient_id = ingredient['ingredient_id']
            ingredient_name = ingredient['ingredient_name']
            in_stock = ingredient['stock']
            total_needed = ingredient_usage[ingredient_id]['total']
            
            # If we already know this item has insufficient ingredients, skip further checks
            if any(item_name in item for item in insufficient_items):
                continue
                
            # Check if the total usage exceeds stock
            if total_needed > in_stock:
                insufficient_items.append(f"{item_name} (Insufficient {ingredient_name})")
                print(f"  - INSUFFICIENT: Need {total_needed} but only have {in_stock}")
    
    if insufficient_items:
        print(f"Found {len(insufficient_items)} items with insufficient ingredients")
    else:
        print("All ingredients available")
        
    return insufficient_items

# the order web page is rendered by GET when the user clicks on the order link from dashboard

# the success order web page is rendered when the barista successfully makes a customer order
# from the order web page. 
'''
@app.route("/order", methods=["GET", "POST"])
def order():
    """Handle order page requests and submissions."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a barista
    if session["role"] != "Barista":
        return render_template("error.html", message="This webpage is for a Barista.")
    

    # loading the form to make/log a customer order
    if request.method == "GET":
        # Get menu items
        menu_items_qry = "SELECT * FROM MenuTable;"
        menu_items = execute_query(menu_items_qry, fetch_type='all')
        
        # Get active promotions
        now = datetime.now()
        promotions_qry = """
        SELECT promotion_id, promotion_name, menu_id, promotion_quantity, 
               promotion_price, promotion_start_time, promotion_end_time
        FROM PromotionTable
        WHERE promotion_start_time <= %s AND promotion_end_time >= %s;
        """
        promotions_data = execute_query(promotions_qry, [now, now], fetch_type='all')
        
        # Format promotions for the template
        promotions = []
        for promo in promotions_data:
            promo_dict = {
                'promotion_id': promo[0],
                'promotion_name': promo[1],
                'menu_id': promo[2],
                'promotion_quantity': promo[3],
                'promotion_price': promo[4],
                'promotion_start_time': promo[5].isoformat(),
                'promotion_end_time': promo[6].isoformat()
            }
            promotions.append(promo_dict)

        return render_template("order.html", menu_items=menu_items, promotions=promotions)
    
    # on successfully entering customer order into the database. 
    # Actually make the order with prep steps to help making the order
    # render order success webpage if order can be processed otherwise error page
    elif request.method == "POST":
        try:
            # Get form data
            order_data = json.loads(request.form.get("order-data", "[]"))
            promotion_data = json.loads(request.form.get("promotion-data", "[]"))
            payment_method = request.form.get("payment_method")
            
            if not order_data:
                return render_template("error.html", message="No items in order")
            
            if not payment_method:
                return render_template("error.html", message="Payment method is required")
            
            # Calculate total amount
            subtotal = sum(float(item.get("subtotal", 0)) for item in order_data)
            
            # Calculate savings from promotions
            # For each promotion, we need to know the regular price to calculate savings
            savings = 0
            for promo in promotion_data:
                promo_id = promo.get("promotion_id")
                
                # Get promotion details from database
                promo_query = "SELECT menu_id, promotion_quantity, promotion_price FROM PromotionTable WHERE promotion_id = %s;"
                promo_details = execute_query(promo_query, [promo_id], fetch_type='one')
                
                if promo_details:
                    menu_id, quantity, promo_price = promo_details
                    
                    # Get regular price of the menu item
                    price_query = "SELECT price FROM MenuTable WHERE menu_id = %s;"
                    price_result = execute_query(price_query, [menu_id], fetch_type='one')
                    
                    if price_result:
                        regular_price = price_result[0]
                        # Calculate savings: regular price * quantity - promotion price
                        item_savings = (regular_price * quantity) - promo_price
                        savings += float(item_savings)
            
            # Final total
            total = subtotal - savings
            
            # Create order in database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                # Begin transaction
                timestamp = datetime.now()
                
                # Insert into OrderTable
                order_insert_query = """
                INSERT INTO OrderTable (payment_method, timestamp, total)
                VALUES (%s, %s, %s) RETURNING order_id;
                """
                cursor.execute(order_insert_query, [payment_method, timestamp, total])
                order_id = cursor.fetchone()[0]
                
                # Insert order details
                for item in order_data:
                    menu_id = item.get("menu_id")
                    quantity = item.get("quantity")
                    subtotal = item.get("subtotal")
                    
                    order_detail_query = """
                    INSERT INTO OrderDetailTable (order_id, menu_id, quantity, subtotal)
                    VALUES (%s, %s, %s, %s);
                    """
                    cursor.execute(order_detail_query, [order_id, menu_id, quantity, subtotal])
                
                # Insert promotion sales details if any
                for promo in promotion_data:
                    promo_id = promo.get("promotion_id")
                    quantity = promo.get("quantity")
                    subtotal = promo.get("subtotal")
                    
                    promo_sale_query = """
                    INSERT INTO PromotionSaleDetailTable (order_id, promotion_id, quantity, subtotal)
                    VALUES (%s, %s, %s, %s);
                    """
                    cursor.execute(promo_sale_query, [order_id, promo_id, quantity, subtotal])
                
                # Commit transaction
                conn.commit()
                
                # Get preparation steps for each item
                preparation_steps = []
                for item in order_data:
                    menu_id = item.get("menu_id")
                    item_name = item.get("name")
                    quantity = item.get("quantity")
                    
                    # Get recipe for this menu item
                    recipe_query = """
                    SELECT recipe_id FROM RecipeTable WHERE menu_id = %s;
                    """
                    recipe_result = execute_query(recipe_query, [menu_id], fetch_type='one')
                    
                    if recipe_result:
                        recipe_id = recipe_result[0]
                        
                        # Get preparation steps
                        steps_query = """
                        SELECT step_number, description 
                        FROM PreparationStepsTable 
                        WHERE recipe_id = %s 
                        ORDER BY step_number;
                        """
                        steps = execute_query(steps_query, [recipe_id], fetch_type='all')
                        
                        # Get ingredients
                        ingredients_query = """
                        SELECT i.ingredient_name, ip.quantity, i.unit
                        FROM IngredientPreparationTable ip
                        JOIN PreparationStepsTable ps ON ip.prep_id = ps.prep_id
                        JOIN IngredientTable i ON ip.ingredient_id = i.ingredient_id
                        WHERE ps.recipe_id = %s;
                        """
                        ingredients = execute_query(ingredients_query, [recipe_id], fetch_type='all')
                        
                        # Format steps and ingredients
                        formatted_steps = [{"description": step[1]} for step in steps]
                        formatted_ingredients = [
                            {"ingredient_name": ing[0], "quantity": ing[1] * quantity, "unit": ing[2]} 
                            for ing in ingredients
                        ]
                        
                        preparation_steps.append({
                            "name": item_name,
                            "quantity": quantity,
                            "steps": formatted_steps,
                            "ingredients": formatted_ingredients
                        })
                
                # Get ordered items details for the success page
                order_items_query = """
                SELECT mt.name, od.quantity, mt.price, od.subtotal
                FROM OrderDetailTable od
                JOIN MenuTable mt ON od.menu_id = mt.menu_id
                WHERE od.order_id = %s;
                """
                order_items_data = execute_query(order_items_query, [order_id], fetch_type='all')
                
                order_items = [
                    {
                        "name": item[0],
                        "quantity": item[1],
                        "unit_price": item[2],
                        "subtotal": item[3]
                    } for item in order_items_data
                ]
                
                return render_template("order_success.html", 
                                      order_id=order_id, 
                                      total=total, 
                                      savings=savings,
                                      order_items=order_items,
                                      preparation_steps=preparation_steps)
                
            except Exception as e:
                conn.rollback()
                print(f"Order processing error: {e}")
                import traceback
                print(traceback.format_exc())
                return render_template("error.html", message=f"Order processing error: {str(e)}")
            finally:
                cursor.close()
                conn.close()
                
        except Exception as e:
            print(f"Order form error: {e}")
            import traceback
            print(traceback.format_exc())
            return render_template("error.html", message=f"Order form error: {str(e)}")
'''

# Modified POST section for the order route to handle promotions correctly
@app.route("/order", methods=["GET", "POST"])
def order():
    """Handle order page requests and submissions."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a barista
    if session["role"] != "Barista":
        return render_template("error.html", message="This webpage is for a Barista.")
    
    # loading the form to make/log a customer order
    if request.method == "GET":
        # Get menu items
        menu_items_qry = "SELECT * FROM MenuTable;"
        menu_items = execute_query(menu_items_qry, fetch_type='all')
        
        # Get active promotions
        now = datetime.now()
        promotions_qry = """
        SELECT promotion_id, promotion_name, menu_id, promotion_quantity, 
               promotion_price, promotion_start_time, promotion_end_time
        FROM PromotionTable
        WHERE promotion_start_time <= %s AND promotion_end_time >= %s;
        """
        promotions_data = execute_query(promotions_qry, [now, now], fetch_type='all')
        
        # Format promotions for the template
        promotions = []
        for promo in promotions_data:
            promo_dict = {
                'promotion_id': promo[0],
                'promotion_name': promo[1],
                'menu_id': promo[2],
                'promotion_quantity': promo[3],
                'promotion_price': promo[4],
                'promotion_start_time': promo[5].isoformat(),
                'promotion_end_time': promo[6].isoformat()
            }
            promotions.append(promo_dict)

        return render_template("order.html", menu_items=menu_items, promotions=promotions)
    
    # on successfully entering customer order into the database. 
    # Actually make the order with prep steps to help making the order
    # render order success webpage if order can be processed otherwise error page
    elif request.method == "POST":
        try:
            # Get form data
            order_data = json.loads(request.form.get("order-data", "[]"))
            promotion_data = json.loads(request.form.get("promotion-data", "[]"))
            payment_method = request.form.get("payment_method")
            
            if not order_data and not promotion_data:
                return render_template("error.html", message="No items in order")
            
            if not payment_method:
                return render_template("error.html", message="Payment method is required")
            
            # Calculate total amount
            subtotal = sum(float(item.get("subtotal", 0)) for item in order_data)
            
            # Add promotion prices
            promo_subtotal = sum(float(promo.get("subtotal", 0)) for promo in promotion_data)
            
            # Final total
            total = subtotal + promo_subtotal
            
            # Create a combined list of all items (regular + promotional) for ingredient checking
            combined_items = []
            
            # Add regular items
            for item in order_data:
                combined_items.append({
                    "menu_id": item.get("menu_id"),
                    "quantity": item.get("quantity"),
                    "name": item.get("name", f"Menu ID {item.get('menu_id')}")
                })
            
            # Add promotional items
            for promo in promotion_data:
                # Get the menu_id for this promotion
                promo_query = "SELECT menu_id, promotion_quantity FROM PromotionTable WHERE promotion_id = %s;"
                promo_details = execute_query(promo_query, [promo.get("promotion_id")], fetch_type='one')
                
                if promo_details:
                    menu_id, promo_quantity = promo_details
                    # Get the item name
                    name_query = "SELECT name FROM MenuTable WHERE menu_id = %s;"
                    name_result = execute_query(name_query, [menu_id], fetch_type='one')
                    
                    item_name = f"Menu ID {menu_id}"
                    if name_result:
                        item_name = name_result[0]
                    
                    # Add to combined items, with quantity being promotion_quantity * how many of this promotion were ordered
                    combined_items.append({
                        "menu_id": menu_id,
                        "quantity": promo_quantity * int(promo.get("quantity", 1)),
                        "name": f"{item_name} (Promotion)"
                    })
            
            # Check if we have enough ingredients
            insufficient_items = check_ingredient_availability(combined_items)
            
            if insufficient_items:
                return render_template("error.html", 
                                      message=f"Cannot fulfill order due to insufficient ingredients: {', '.join(insufficient_items)}")
            
            # Create order in database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            try:
                # Begin transaction
                timestamp = datetime.now()
                
                # Insert into OrderTable
                order_insert_query = """
                INSERT INTO OrderTable (payment_method, timestamp, total)
                VALUES (%s, %s, %s) RETURNING order_id;
                """
                cursor.execute(order_insert_query, [payment_method, timestamp, total])
                order_id = cursor.fetchone()[0]
                
                # Insert regular order details
                for item in order_data:
                    menu_id = item.get("menu_id")
                    quantity = item.get("quantity")
                    subtotal = item.get("subtotal")
                    
                    order_detail_query = """
                    INSERT INTO OrderDetailTable (order_id, menu_id, quantity, subtotal)
                    VALUES (%s, %s, %s, %s);
                    """
                    cursor.execute(order_detail_query, [order_id, menu_id, quantity, subtotal])
                
                # Insert promotion sales details
                for promo in promotion_data:
                    promo_id = promo.get("promotion_id")
                    quantity = promo.get("quantity", 1)  # Default to 1 if not specified
                    subtotal = promo.get("subtotal")
                    
                    promo_sale_query = """
                    INSERT INTO PromotionSaleDetailTable (order_id, promotion_id, quantity, subtotal)
                    VALUES (%s, %s, %s, %s);
                    """
                    cursor.execute(promo_sale_query, [order_id, promo_id, quantity, subtotal])
                
                # Update ingredient inventory for all items (both regular and promotional)
                for item in combined_items:
                    menu_id = item.get("menu_id")
                    quantity = int(item.get("quantity"))
                    
                    # Get all ingredients used for this menu item
                    ingredients_query = """
                    SELECT ipt.ingredient_id, ipt.quantity
                    FROM MenuTable m
                    JOIN RecipeTable r ON m.menu_id = r.menu_id
                    JOIN PreparationStepsTable ps ON r.recipe_id = ps.recipe_id
                    JOIN IngredientPreparationTable ipt ON ps.prep_id = ipt.prep_id
                    WHERE m.menu_id = %s;
                    """
                    ingredients = execute_query(ingredients_query, [menu_id], 'all')
                    
                    # Deduct ingredients from inventory
                    for ingredient in ingredients:
                        ingredient_id, ingredient_qty = ingredient
                        total_used = ingredient_qty * quantity
                        
                        update_inventory_query = """
                        UPDATE IngredientTable
                        SET amount_in_stock = amount_in_stock - %s
                        WHERE ingredient_id = %s;
                        """
                        cursor.execute(update_inventory_query, [total_used, ingredient_id])
                
                # Commit transaction
                conn.commit()
                
                # Get preparation steps for order success page
                preparation_steps = []
                
                # Process regular items for preparation steps
                for item in order_data:
                    menu_id = item.get("menu_id")
                    item_name = item.get("name")
                    quantity = item.get("quantity")
                    
                    # Get recipe for this menu item
                    recipe_query = """
                    SELECT recipe_id FROM RecipeTable WHERE menu_id = %s;
                    """
                    recipe_result = execute_query(recipe_query, [menu_id], fetch_type='one')
                    
                    if recipe_result:
                        recipe_id = recipe_result[0]
                        
                        # Get preparation steps for this recipe
                        steps_query = """
                        SELECT step_number, description, prep_id
                        FROM PreparationStepsTable
                        WHERE recipe_id = %s
                        ORDER BY step_number;
                        """
                        prep_steps = execute_query(steps_query, [recipe_id], fetch_type='all')
                        
                        formatted_steps = []
                        ingredients_for_item = []
                        
                        # Process each step
                        for step in prep_steps:
                            step_number, description, prep_id = step
                            formatted_steps.append({
                                "description": description
                            })
                            
                            # Get ingredients for this preparation step
                            ingredients_query = """
                            SELECT i.ingredient_name, ipt.quantity, i.unit
                            FROM IngredientPreparationTable ipt
                            JOIN IngredientTable i ON ipt.ingredient_id = i.ingredient_id
                            WHERE ipt.prep_id = %s;
                            """
                            ingredients = execute_query(ingredients_query, [prep_id], fetch_type='all')
                            
                            for ingredient in ingredients:
                                ingredient_name, ingredient_qty, unit = ingredient
                                ingredients_for_item.append({
                                    "ingredient_name": ingredient_name,
                                    "quantity": ingredient_qty,
                                    "unit": unit
                                })
                        
                        # Add this item's preparation info to the list
                        preparation_steps.append({
                            "name": item_name,
                            "quantity": quantity,
                            "steps": formatted_steps,
                            "ingredients": ingredients_for_item
                        })
                
                # Process promotional items for preparation steps
                for promo in promotion_data:
                    promo_id = promo.get("promotion_id")
                    promo_quantity = int(promo.get("quantity", 1))
                    
                    # Get promotion details
                    promo_query = """
                    SELECT p.menu_id, p.promotion_name, p.promotion_quantity, m.name
                    FROM PromotionTable p
                    JOIN MenuTable m ON p.menu_id = m.menu_id
                    WHERE p.promotion_id = %s;
                    """
                    promo_details = execute_query(promo_query, [promo_id], fetch_type='one')
                    
                    if promo_details:
                        menu_id, promotion_name, promo_item_quantity, item_name = promo_details
                        total_quantity = promo_item_quantity * promo_quantity
                        
                        # Get recipe for this menu item
                        recipe_query = """
                        SELECT recipe_id FROM RecipeTable WHERE menu_id = %s;
                        """
                        recipe_result = execute_query(recipe_query, [menu_id], fetch_type='one')
                        
                        if recipe_result:
                            recipe_id = recipe_result[0]
                            
                            # Get preparation steps for this recipe
                            steps_query = """
                            SELECT step_number, description, prep_id
                            FROM PreparationStepsTable
                            WHERE recipe_id = %s
                            ORDER BY step_number;
                            """
                            prep_steps = execute_query(steps_query, [recipe_id], fetch_type='all')
                            
                            formatted_steps = []
                            ingredients_for_item = []
                            
                            # Process each step
                            for step in prep_steps:
                                step_number, description, prep_id = step
                                formatted_steps.append({
                                    "description": description
                                })
                                
                                # Get ingredients for this preparation step
                                ingredients_query = """
                                SELECT i.ingredient_name, ipt.quantity, i.unit
                                FROM IngredientPreparationTable ipt
                                JOIN IngredientTable i ON ipt.ingredient_id = i.ingredient_id
                                WHERE ipt.prep_id = %s;
                                """
                                ingredients = execute_query(ingredients_query, [prep_id], fetch_type='all')
                                
                                for ingredient in ingredients:
                                    ingredient_name, ingredient_qty, unit = ingredient
                                    ingredients_for_item.append({
                                        "ingredient_name": ingredient_name,
                                        "quantity": ingredient_qty,
                                        "unit": unit
                                    })
                            
                            # Add this promotional item's preparation info to the list
                            preparation_steps.append({
                                "name": f"{item_name} (Promotion: {promotion_name})",
                                "quantity": total_quantity,
                                "steps": formatted_steps,
                                "ingredients": ingredients_for_item
                            })
                
                # Format order items for display
                display_items = []
                
                # Regular items
                for item in order_data:
                    display_items.append({
                        "name": item.get("name"),
                        "quantity": item.get("quantity"),
                        "unit_price": item.get("price"),
                        "subtotal": item.get("subtotal")
                    })
                
                # Promotional items
                for promo in promotion_data:
                    promo_id = promo.get("promotion_id")
                    promo_query = "SELECT promotion_name, promotion_price FROM PromotionTable WHERE promotion_id = %s;"
                    promo_info = execute_query(promo_query, [promo_id], fetch_type='one')
                    
                    if promo_info:
                        display_items.append({
                            "name": f"{promo_info[0]} (Promotion)",
                            "quantity": promo.get("quantity", 1),
                            "unit_price": promo_info[1],
                            "subtotal": promo.get("subtotal")
                        })
                
                # Calculate savings (if any)
                savings = 0
                for promo in promotion_data:
                    if "discount" in promo:
                        savings += float(promo.get("discount", 0))
                
                return render_template("order_success.html", 
                                      order_id=order_id, 
                                      total=total, 
                                      savings=savings,
                                      order_items=display_items,
                                      preparation_steps=preparation_steps)
                
            except Exception as e:
                conn.rollback()
                print(f"Order processing error: {e}")
                import traceback
                print(traceback.format_exc())
                return render_template("error.html", message=f"Order processing error: {str(e)}")
            finally:
                cursor.close()
                conn.close()
                
        except Exception as e:
            print(f"Order form error: {e}")
            import traceback
            print(traceback.format_exc())
            return render_template("error.html", message=f"Order form error: {str(e)}")
#==================================== Managing employees by managers ============================

# this gets run from the dashboard webpage via a link to manage employees
# renders the manage employee webpage 
@app.route("/manage_employees")
def manage_employees():
    """Render the employee management page (Manager only)."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Get all employees with their role-specific information
    employees_query = """
    SELECT e.ssn, e.role, e.name, e.email, e.salary,
           CASE WHEN e.role = 'Manager' THEN m.ownership_percent ELSE NULL END as ownership, e.password
    FROM EmployeeTable e
    LEFT JOIN ManagerTable m ON e.ssn = m.ssn AND e.role = m.role
    ORDER BY e.name;
    """
    employees = execute_query(employees_query, fetch_type='all')
    if not employees:
        return render_template("error.html", message="Couldn't retrieve employee information")
    
    # Get barista schedules
    barista_schedules_query = """
    SELECT ssn, day, start_time, end_time
    FROM BaristaTable
    ORDER BY ssn, day, start_time;
    """
    barista_schedules = execute_query(barista_schedules_query, fetch_type='all')
    
    # Organize barista schedules by SSN
    schedules_by_ssn = {}
    if barista_schedules:
        for schedule in barista_schedules:
            ssn = schedule[0]
            day = schedule[1]
            start_time = schedule[2]
            end_time = schedule[3]
            
            if ssn not in schedules_by_ssn:
                schedules_by_ssn[ssn] = []
            
            schedules_by_ssn[ssn].append({
                'day': day,
                'start_time': start_time,
                'end_time': end_time
            })
    
    return render_template("manage_employees3.html", 
                           employees=employees, 
                           barista_schedules=schedules_by_ssn)

'''
@app.route("/add_employee", methods=["POST"])
def add_employee():
    """Add a new employee (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ssn = request.form.get("ssn")
    name = request.form.get("name")
    role = request.form.get("role")
    email = request.form.get("email")
    password = request.form.get("password")
    salary = request.form.get("salary")
    
    # Validate inputs
    if not all([ssn, name, role, email, password,  salary]):
        return render_template("error.html", message="All fields are required")
    
    try:
        # Start transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if employee already exists
        check_query = "SELECT 1 FROM EmployeeTable WHERE ssn = %s AND role = %s"
        cursor.execute(check_query, [ssn, role])
        if cursor.fetchone():
            conn.close()
            return render_template("error.html", message="Employee with this SSN and role already exists")
        
        # Insert into EmployeeTable
        insert_query = """
        INSERT INTO EmployeeTable (ssn, role, name, email, password, salary)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, [ssn, role, name, email, password, salary])
        
        # If role is Manager, also insert into ManagerTable
        if role == "Manager":
            ownership = request.form.get("ownership")
            if not ownership:
                conn.rollback()
                conn.close()
                return render_template("error.html", message="Ownership percentage is required for managers")
            
            manager_query = """
            INSERT INTO ManagerTable (ssn, role, ownership_percent)
            VALUES (%s, %s, %s)
            """
            cursor.execute(manager_query, [ssn, role, ownership])
        
        # If role is Barista, handle availability schedule
        if role == "Barista":
            # Get barista schedule data
            schedule_days = request.form.getlist("schedule_day")
            schedule_starts = request.form.getlist("schedule_start")
            schedule_ends = request.form.getlist("schedule_end")
            
            if not (schedule_days and schedule_starts and schedule_ends):
                conn.rollback()
                conn.close()
                return render_template("error.html", message="At least one availability schedule is required for baristas")
            
            # Insert each schedule entry
            for i in range(len(schedule_days)):
                if i < len(schedule_starts) and i < len(schedule_ends):
                    day = schedule_days[i]
                    start_time = schedule_starts[i]
                    end_time = schedule_ends[i]
                    
                    if all([day, start_time, end_time]):
                        barista_query = """
                        INSERT INTO BaristaTable (ssn, role, day, start_time, end_time)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(barista_query, [ssn, role, day, start_time, end_time])
        
        # Commit transaction
        conn.commit()
        conn.close()
        
        # Redirect back to employee management
        return redirect("/manage_employees")
        
    except Exception as e:
        import traceback
        print(f"Error adding employee: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return render_template("error.html", message=f"Error adding employee: {str(e)}")
'''
'''# Allows manager to edit and make changes for the employees from manage employee webpage
@app.route("/update_employee", methods=["POST"])
def update_employee():
    """Update an existing employee (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ssn = request.form.get("ssn")
    name = request.form.get("name")
    role = request.form.get("role")
    email = request.form.get("email")
    password = request.form.get("password")
    salary = request.form.get("salary")
    original_ssn = request.form.get("original_ssn")
    original_role = request.form.get("original_role")
    
    # Validate inputs
    if not all([ssn, name, role, email, password, salary, original_ssn, original_role]):
        return render_template("error.html", message="All fields are required")
    
    try:
        # Start transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update EmployeeTable
        update_query = """
        UPDATE EmployeeTable
        SET name = %s, email = %s, password = %s, salary = %s, 
        WHERE ssn = %s AND role = %s
        """
        cursor.execute(update_query, [name, email, password, salary, original_ssn, original_role])
        
        # Handle role changes if needed
        if role != original_role:
            # For simplicity, we'll keep the original role
            role = original_role
            
        # If role is Manager, update ManagerTable
        if role == "Manager":
            ownership = request.form.get("ownership")
            if not ownership:
                conn.rollback()
                conn.close()
                return render_template("error.html", message="Ownership percentage is required for managers")
            
            # Check if manager record exists
            check_manager = "SELECT 1 FROM ManagerTable WHERE ssn = %s AND role = %s"
            cursor.execute(check_manager, [original_ssn, "Manager"])
            
            if cursor.fetchone():
                # Update existing manager record
                manager_update = """
                UPDATE ManagerTable
                SET ownership_percent = %s
                WHERE ssn = %s AND role = %s
                """
                cursor.execute(manager_update, [ownership, original_ssn, "Manager"])
            else:
                # Insert new manager record
                manager_insert = """
                INSERT INTO ManagerTable (ssn, role, ownership_percent)
                VALUES (%s, %s, %s)
                """
                cursor.execute(manager_insert, [original_ssn, "Manager", ownership])
        
        # If role is Barista, handle schedule updates
        if role == "Barista":
            # First, delete all existing schedules for this barista
            delete_schedules = """
            DELETE FROM BaristaTable
            WHERE ssn = %s AND role = %s
            """
            cursor.execute(delete_schedules, [original_ssn, "Barista"])
            
            # Get new barista schedule data
            schedule_days = request.form.getlist("schedule_day")
            schedule_starts = request.form.getlist("schedule_start")
            schedule_ends = request.form.getlist("schedule_end")
            
            if not (schedule_days and schedule_starts and schedule_ends):
                conn.rollback()
                conn.close()
                return render_template("error.html", message="At least one availability schedule is required for baristas")
            
            # Insert each new schedule entry
            for i in range(len(schedule_days)):
                if i < len(schedule_starts) and i < len(schedule_ends):
                    day = schedule_days[i]
                    start_time = schedule_starts[i]
                    end_time = schedule_ends[i]
                    
                    if all([day, start_time, end_time]):
                        barista_query = """
                        INSERT INTO BaristaTable (ssn, role, day, start_time, end_time)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(barista_query, [original_ssn, "Barista", day, start_time, end_time])
        
        # Commit transaction
        conn.commit()
        conn.close()
        
        # Redirect back to employee management
        return redirect("/manage_employees")
        
    except Exception as e:
        import traceback
        print(f"Error updating employee: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return render_template("error.html", message=f"Error updating employee: {str(e)}")
'''

@app.route("/add_employee", methods=["POST"])
def add_employee():
    """Add a new employee (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ssn = request.form.get("ssn")
    name = request.form.get("name")
    role = request.form.get("role")
    email = request.form.get("email")
    password = request.form.get("password")
    salary = request.form.get("salary")
    
    # Validate inputs
    if not all([ssn, name, role, email, password, salary]):
        return render_template("error.html", message="All fields are required")
    
    try:
        # Start transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if employee already exists
        check_query = "SELECT 1 FROM EmployeeTable WHERE ssn = %s AND role = %s"
        cursor.execute(check_query, [ssn, role])
        if cursor.fetchone():
            conn.close()
            return render_template("error.html", message="Employee with this SSN and role already exists")
        
        # Insert into EmployeeTable
        insert_query = """
        INSERT INTO EmployeeTable (ssn, role, name, email, password, salary)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, [ssn, role, name, email, password, salary])
        
        # If role is Manager, also insert into ManagerTable
        if role == "Manager":
            ownership = request.form.get("ownership")
            if not ownership:
                conn.rollback()
                conn.close()
                return render_template("error.html", message="Ownership percentage is required for managers")
            
            manager_query = """
            INSERT INTO ManagerTable (ssn, role, ownership_percent)
            VALUES (%s, %s, %s)
            """
            cursor.execute(manager_query, [ssn, role, ownership])
        
        # If role is Barista, handle availability schedule
        if role == "Barista":
            # Get barista schedule data
            schedule_days = request.form.getlist("schedule_day")
            schedule_starts = request.form.getlist("schedule_start")
            schedule_ends = request.form.getlist("schedule_end")
            
            if not (schedule_days and schedule_starts and schedule_ends):
                conn.rollback()
                conn.close()
                return render_template("error.html", message="At least one availability schedule is required for baristas")
            
            # Insert each schedule entry
            for i in range(len(schedule_days)):
                if i < len(schedule_starts) and i < len(schedule_ends):
                    day = schedule_days[i]
                    start_time = schedule_starts[i]
                    end_time = schedule_ends[i]
                    
                    if all([day, start_time, end_time]):
                        barista_query = """
                        INSERT INTO BaristaTable (ssn, role, day, start_time, end_time)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(barista_query, [ssn, role, day, start_time, end_time])
        
        # Commit transaction
        conn.commit()
        conn.close()
        
        # Redirect back to employee management
        return redirect("/manage_employees")
        
    except Exception as e:
        import traceback
        print(f"Error adding employee: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return render_template("error.html", message=f"Error adding employee: {str(e)}")

@app.route("/update_employee", methods=["POST"])
def update_employee():
    """Update an existing employee (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ssn = request.form.get("ssn")
    name = request.form.get("name")
    role = request.form.get("role")
    email = request.form.get("email")
    password = request.form.get("password")
    salary = request.form.get("salary")
    original_ssn = request.form.get("original_ssn")
    original_role = request.form.get("original_role")
    
    # Validate inputs
    if not all([ssn, name, role, email, password, salary, original_ssn, original_role]):
        return render_template("error.html", message="All fields are required")
    
    try:
        # Start transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update EmployeeTable - FIXED: removed trailing comma
        update_query = """
        UPDATE EmployeeTable
        SET name = %s, email = %s, password = %s, salary = %s
        WHERE ssn = %s AND role = %s
        """
        cursor.execute(update_query, [name, email, password, salary, original_ssn, original_role])
        
        # Handle role changes if needed
        if role != original_role:
            # For simplicity, we'll keep the original role
            role = original_role
            
        # If role is Manager, update ManagerTable
        if role == "Manager":
            ownership = request.form.get("ownership")
            if not ownership:
                conn.rollback()
                conn.close()
                return render_template("error.html", message="Ownership percentage is required for managers")
            
            # Check if manager record exists
            check_manager = "SELECT 1 FROM ManagerTable WHERE ssn = %s AND role = %s"
            cursor.execute(check_manager, [original_ssn, "Manager"])
            
            if cursor.fetchone():
                # Update existing manager record
                manager_update = """
                UPDATE ManagerTable
                SET ownership_percent = %s
                WHERE ssn = %s AND role = %s
                """
                cursor.execute(manager_update, [ownership, original_ssn, "Manager"])
            else:
                # Insert new manager record
                manager_insert = """
                INSERT INTO ManagerTable (ssn, role, ownership_percent)
                VALUES (%s, %s, %s)
                """
                cursor.execute(manager_insert, [original_ssn, "Manager", ownership])
        
        # If role is Barista, handle schedule updates
        if role == "Barista":
            # First, delete all existing schedules for this barista
            delete_schedules = """
            DELETE FROM BaristaTable
            WHERE ssn = %s AND role = %s
            """
            cursor.execute(delete_schedules, [original_ssn, "Barista"])
            
            # Get new barista schedule data
            schedule_days = request.form.getlist("schedule_day")
            schedule_starts = request.form.getlist("schedule_start")
            schedule_ends = request.form.getlist("schedule_end")
            
            if not (schedule_days and schedule_starts and schedule_ends):
                conn.rollback()
                conn.close()
                return render_template("error.html", message="At least one availability schedule is required for baristas")
            
            # Insert each new schedule entry
            for i in range(len(schedule_days)):
                if i < len(schedule_starts) and i < len(schedule_ends):
                    day = schedule_days[i]
                    start_time = schedule_starts[i]
                    end_time = schedule_ends[i]
                    
                    if all([day, start_time, end_time]):
                        barista_query = """
                        INSERT INTO BaristaTable (ssn, role, day, start_time, end_time)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(barista_query, [original_ssn, "Barista", day, start_time, end_time])
        
        # Commit transaction
        conn.commit()
        conn.close()
        
        # Redirect back to employee management
        return redirect("/manage_employees")
        
    except Exception as e:
        import traceback
        print(f"Error updating employee: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return render_template("error.html", message=f"Error updating employee: {str(e)}")
# Allows manager to delete a record of an employee from manage employee webpage
@app.route("/delete_employee", methods=["POST"])
def delete_employee():
    """Delete an employee (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ssn = request.form.get("ssn")
    role = request.form.get("role")
    
    # Validate inputs
    if not all([ssn, role]):
        return render_template("error.html", message="SSN and role are required")
    
    try:
        # Delete the employee (cascade should handle related tables)
        delete_query = "DELETE FROM EmployeeTable WHERE ssn = %s AND role = %s"
        result = execute_query(delete_query, [ssn, role])
        
        if result <= 0:
            return render_template("error.html", message="Failed to delete employee or employee not found")
        
        # Redirect back to employee management
        return redirect("/manage_employees")
        
    except Exception as e:
        import traceback
        print(f"Error deleting employee: {str(e)}")
        print(traceback.format_exc())
        return render_template("error.html", message=f"Error deleting employee: {str(e)}")

#==================================== Managing inventory by managers ============================

# render the web page manage ingredients from link on dashboard only by managers.
@app.route("/ingredients")
def manage_ingredients():
    """Render the ingredient management page (Manager only)."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Get all ingredients
    ingredients_query = """
    SELECT ingredient_id, ingredient_name, unit, price_per_unit, amount_in_stock
    FROM IngredientTable
    ORDER BY ingredient_name;
    """
    ingredients = execute_query(ingredients_query, fetch_type='all')
    
    # Get current balance
    balance_query = """
    SELECT balance FROM AccountingTable 
    ORDER BY timestamp DESC LIMIT 1;
    """
    balance_result = execute_query(balance_query, fetch_type='one')
    current_balance = balance_result[0] if balance_result else 0.0
    
    return render_template("manage_ingredients.html", ingredients=ingredients, current_balance=current_balance)

# upon adding a new ingredient from the manage ingredients webpage
@app.route("/add_ingredient", methods=["POST"])
def add_ingredient():
    """Add a new ingredient (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    name = request.form.get("name")
    unit = request.form.get("unit")
    price = request.form.get("price")
    initial_stock = request.form.get("initial_stock")
    
    # Validate inputs
    if not all([name, unit, price, initial_stock]):
        return render_template("error.html", message="All fields are required")
    
    try:
        # Insert into IngredientTable
        insert_query = """
        INSERT INTO IngredientTable (ingredient_name, unit, price_per_unit, amount_in_stock)
        VALUES (%s, %s, %s, %s)
        """
        result = execute_query(insert_query, [name, unit, price, initial_stock])
        
        if result <= 0:
            return render_template("error.html", message="Failed to add ingredient")
        
        # If there's initial stock, update accounting
        if float(initial_stock) > 0:
            # Calculate the cost
            total_cost = float(price) * float(initial_stock)
            
            # Get current balance
            balance_query = """
            SELECT balance FROM AccountingTable 
            ORDER BY timestamp DESC LIMIT 1;
            """
            balance_result = execute_query(balance_query, fetch_type='one')
            
            if balance_result:
                current_balance = float(balance_result[0])
                new_balance = current_balance - total_cost
            else:
                # If no previous balance, start with negative of this purchase
                new_balance = -total_cost
            
            # Add accounting entry
            accounting_query = """
            INSERT INTO AccountingTable (timestamp, balance)
            VALUES (NOW(), %s);
            """
            execute_query(accounting_query, [new_balance])
        
        # Redirect back to ingredient management
        return redirect("/ingredients")
        
    except Exception as e:
        import traceback
        print(f"Error adding ingredient: {str(e)}")
        print(traceback.format_exc())
        return render_template("error.html", message=f"Error adding ingredient: {str(e)}")

# upon buying new stock for the ingredients from the manage ingredients webpage
@app.route("/buy_ingredient", methods=["POST"])
def buy_ingredient():
    """Purchase more of an existing ingredient (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    ingredient_id = request.form.get("ingredient_id")
    quantity = request.form.get("quantity")
    
    # Validate inputs
    if not all([ingredient_id, quantity]):
        return render_template("error.html", message="Ingredient ID and quantity are required")
    
    try:
        # Start transaction
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current ingredient info
        ingredient_query = """
        SELECT ingredient_name, price_per_unit, amount_in_stock
        FROM IngredientTable
        WHERE ingredient_id = %s;
        """
        cursor.execute(ingredient_query, [ingredient_id])
        ingredient_info = cursor.fetchone()
        
        if not ingredient_info:
            conn.close()
            return render_template("error.html", message="Ingredient not found")
        
        ingredient_name, price_per_unit, current_stock = ingredient_info
        
        # Calculate purchase cost
        purchase_quantity = float(quantity)
        purchase_cost = purchase_quantity * float(price_per_unit)
        
        # Check if there's enough balance
        balance_query = """
        SELECT balance FROM AccountingTable 
        ORDER BY timestamp DESC LIMIT 1;
        """
        cursor.execute(balance_query)
        balance_result = cursor.fetchone()
        
        if not balance_result:
            # No previous accounting record, start with negative of this purchase
            current_balance = 0
        else:
            current_balance = float(balance_result[0])
        
        new_balance = current_balance - purchase_cost
        
        # Update the ingredient stock
        new_stock = float(current_stock) + purchase_quantity
        update_stock_query = """
        UPDATE IngredientTable
        SET amount_in_stock = %s
        WHERE ingredient_id = %s;
        """
        cursor.execute(update_stock_query, [new_stock, ingredient_id])
        
        # Add accounting entry
        accounting_query = """
        INSERT INTO AccountingTable (timestamp, balance)
        VALUES (NOW(), %s);
        """
        cursor.execute(accounting_query, [new_balance])
        
        # Commit transaction
        conn.commit()
        conn.close()
        
        # Redirect back to ingredient management
        return redirect("/ingredients")
        
    except Exception as e:
        import traceback
        print(f"Error purchasing ingredient: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.rollback()
            conn.close()
        return render_template("error.html", message=f"Error purchasing ingredient: {str(e)}")
           
#==================================== Managing promotions by managers ============================

@app.route("/promotions", methods=["GET"])
def promotions():
    """Render the promotions management page (Manager only)."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Get all menu items for the dropdown
    menu_items_qry = "SELECT * FROM MenuTable ORDER BY name;"
    menu_items = execute_query(menu_items_qry, fetch_type='all')
    
    # Get all current promotions with menu item details
    promotions_qry = """
    SELECT p.promotion_id, p.promotion_name, p.menu_id, m.name as menu_name,
           p.promotion_quantity, p.promotion_price, 
           p.promotion_start_time, p.promotion_end_time,
           p.promotion_description
    FROM PromotionTable p
    JOIN MenuTable m ON p.menu_id = m.menu_id
    ORDER BY p.promotion_end_time DESC;
    """
    promotions_data = execute_query(promotions_qry, fetch_type='all')
    
    # Format promotions for the template
    promotions = []
    now = datetime.now()
    
    for promo in promotions_data:
        start_time = promo[6]
        end_time = promo[7]
        
        promo_dict = {
            'promotion_id': promo[0],
            'promotion_name': promo[1],
            'menu_id': promo[2],
            'menu_name': promo[3],
            'promotion_quantity': promo[4],
            'promotion_price': promo[5],
            'promotion_start_time': start_time,
            'promotion_end_time': end_time,
            'promotion_description': promo[8] if len(promo) > 8 else None,
            'is_active': (start_time <= now <= end_time),
            'is_upcoming': (start_time > now),
            'is_expired': (end_time < now)
        }
        promotions.append(promo_dict)
    
    # Get analytics data
    active_count = sum(1 for p in promotions if p['is_active'])
    
    # Get promotion usage statistics
    usage_qry = """
    SELECT p.promotion_id, p.promotion_name, COUNT(psd.promotion_sale_detail_id) as usage_count, 
           SUM(psd.subtotal) as total_sales
    FROM PromotionTable p
    LEFT JOIN PromotionSaleDetailTable psd ON p.promotion_id = psd.promotion_id
    GROUP BY p.promotion_id, p.promotion_name
    ORDER BY usage_count DESC;
    """
    usage_data = execute_query(usage_qry, fetch_type='all')
    
    # Calculate total usage and find most popular promotion
    total_usage = 0
    most_popular = None
    revenue_impact = 0
    
    if usage_data:
        for usage in usage_data:
            count = usage[2] if usage[2] else 0
            total_usage += count
            
            if count > 0 and (most_popular is None or count > most_popular['count']):
                most_popular = {
                    'promotion_id': usage[0],
                    'promotion_name': usage[1],
                    'count': count
                }
                
            # Add sales to revenue impact
            if usage[3]:
                revenue_impact += float(usage[3])
    
    return render_template("manager_promotions.html", 
                          menu_items=menu_items, 
                          promotions=promotions,
                          active_count=active_count,
                          total_usage=total_usage,
                          most_popular=most_popular,
                          revenue_impact=revenue_impact)

@app.route("/promotions/create", methods=["POST"])
def create_promotion():
    """Create a new promotion (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    promotion_name = request.form.get("promotion_name")
    menu_id = request.form.get("menu_id")
    promotion_quantity = request.form.get("promotion_quantity")
    promotion_price = request.form.get("promotion_price")
    promotion_start_time = request.form.get("promotion_start_time")
    promotion_end_time = request.form.get("promotion_end_time")
    
    # Validate inputs
    if not all([promotion_name, menu_id, promotion_quantity, 
                promotion_price, promotion_start_time, promotion_end_time]):
        return render_template("error.html", message="All fields are required")
    
    # Convert to appropriate types
    try:
        menu_id = int(menu_id)
        promotion_quantity = int(promotion_quantity)
        promotion_price = float(promotion_price)
        # Parse datetime strings to datetime objects
        start_datetime = datetime.fromisoformat(promotion_start_time)
        end_datetime = datetime.fromisoformat(promotion_end_time)
    except ValueError as e:
        return render_template("error.html", message=f"Invalid input format: {str(e)}")
    
    # Ensure end time is after start time
    if end_datetime <= start_datetime:
        return render_template("error.html", message="End time must be after start time")
    
    # Insert the promotion
    insert_qry = """
    INSERT INTO PromotionTable 
    (promotion_name, menu_id, promotion_quantity, promotion_price, 
     promotion_start_time, promotion_end_time)
    VALUES (%s, %s, %s, %s, %s, %s);
    """
    
    result = execute_query(
        insert_qry, 
        [promotion_name, menu_id, promotion_quantity, promotion_price, 
         start_datetime, end_datetime]
    )
    
    if result == -1:
        return render_template("error.html", message="Failed to create promotion")
    
    return redirect("/promotions")

@app.route("/promotions/add", methods=["POST"])
def add_promotion():
    """Create a new promotion (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    promotion_name = request.form.get("promotion_name")
    menu_id = request.form.get("menu_id")
    promotion_quantity = request.form.get("promotion_quantity")
    promotion_price = request.form.get("promotion_price")
    promotion_start_time = request.form.get("promotion_start_time")
    promotion_end_time = request.form.get("promotion_end_time")
    promotion_description = request.form.get("promotion_description", "")
    
    # Validate inputs
    if not all([promotion_name, menu_id, promotion_quantity, 
                promotion_price, promotion_start_time, promotion_end_time]):
        return render_template("error.html", message="All required fields must be filled")
    
    # Convert to appropriate types
    try:
        menu_id = int(menu_id)
        promotion_quantity = int(promotion_quantity)
        promotion_price = float(promotion_price)
        # Parse datetime strings to datetime objects
        start_datetime = datetime.fromisoformat(promotion_start_time)
        end_datetime = datetime.fromisoformat(promotion_end_time)
    except ValueError as e:
        return render_template("error.html", message=f"Invalid input format: {str(e)}")
    
    # Ensure end time is after start time
    if end_datetime <= start_datetime:
        return render_template("error.html", message="End time must be after start time")
    
    # Insert the promotion
    insert_qry = """
    INSERT INTO PromotionTable 
    (promotion_name, menu_id, promotion_quantity, promotion_price, 
     promotion_start_time, promotion_end_time, promotion_description)
    VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    
    result = execute_query(
        insert_qry, 
        [promotion_name, menu_id, promotion_quantity, promotion_price, 
         start_datetime, end_datetime, promotion_description]
    )
    
    if result == -1:
        return render_template("error.html", message="Failed to create promotion")
    
    return redirect("/promotions")

@app.route("/promotion/<int:promotion_id>", methods=["GET"])
def get_promotion(promotion_id):
    """Get promotion details by ID (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return jsonify({"error": "Unauthorized"}), 401
    
    # Query the promotion
    promo_qry = """
    SELECT p.promotion_id, p.promotion_name, p.menu_id, m.name as menu_name,
           p.promotion_quantity, p.promotion_price, 
           p.promotion_start_time, p.promotion_end_time, p.promotion_description
    FROM PromotionTable p
    JOIN MenuTable m ON p.menu_id = m.menu_id
    WHERE p.promotion_id = %s;
    """
    promo = execute_query(promo_qry, [promotion_id], fetch_type='one')
    
    if not promo:
        return jsonify({"error": "Promotion not found"}), 404
    
    # Format the data for JSON response
    promotion_data = {
        'promotion_id': promo[0],
        'promotion_name': promo[1],
        'menu_id': promo[2],
        'menu_name': promo[3],
        'promotion_quantity': promo[4],
        'promotion_price': float(promo[5]),
        'promotion_start_time': promo[6].isoformat(),
        'promotion_end_time': promo[7].isoformat(),
        'promotion_description': promo[8] if len(promo) > 8 else ""
    }
    
    return jsonify(promotion_data)

@app.route("/promotions/update", methods=["POST"])
def update_promotion():
    """Update an existing promotion (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    # Get form data
    promotion_id = request.form.get("promotion_id")
    promotion_name = request.form.get("promotion_name")
    promotion_quantity = request.form.get("promotion_quantity")
    promotion_price = request.form.get("promotion_price")
    promotion_start_time = request.form.get("promotion_start_time")
    promotion_end_time = request.form.get("promotion_end_time")
    promotion_description = request.form.get("promotion_description", "")
    
    # Validate inputs
    if not all([promotion_id, promotion_name, promotion_quantity, 
                promotion_price, promotion_start_time, promotion_end_time]):
        return render_template("error.html", message="All required fields must be filled")
    
    # Convert to appropriate types
    try:
        promotion_id = int(promotion_id)
        promotion_quantity = int(promotion_quantity)
        promotion_price = float(promotion_price)
        # Parse datetime strings to datetime objects
        start_datetime = datetime.fromisoformat(promotion_start_time)
        end_datetime = datetime.fromisoformat(promotion_end_time)
    except ValueError as e:
        return render_template("error.html", message=f"Invalid input format: {str(e)}")
    
    # Ensure end time is after start time
    if end_datetime <= start_datetime:
        return render_template("error.html", message="End time must be after start time")
    
    # Update the promotion
    update_qry = """
    UPDATE PromotionTable 
    SET promotion_name = %s,
        promotion_quantity = %s,
        promotion_price = %s,
        promotion_start_time = %s,
        promotion_end_time = %s,
        promotion_description = %s
    WHERE promotion_id = %s;
    """
    
    result = execute_query(
        update_qry, 
        [promotion_name, promotion_quantity, promotion_price, 
         start_datetime, end_datetime, promotion_description, promotion_id]
    )
    
    if result == -1:
        return render_template("error.html", message="Failed to update promotion")
    
    return redirect("/promotions")

@app.route("/promotions/delete", methods=["POST"])
def delete_promotion():
    """Delete a promotion (Manager only)."""
    if "ssn" not in session or "role" not in session or session["role"] != "Manager":
        return redirect("/")
    
    promotion_id = request.form.get("promotion_id")
    if not promotion_id:
        return render_template("error.html", message="Promotion ID required")
    
    delete_qry = "DELETE FROM PromotionTable WHERE promotion_id = %s;"
    result = execute_query(delete_qry, [promotion_id])
    
    if result == -1:
        return render_template("error.html", message="Failed to delete promotion")
    
    return redirect("/promotions")



#==================================== Manager Accounting report ============================

# Allows the manager to see the history of account balances. limits by 50 descending
# avaiLble from dashboard, renders on accounting reports webpage
@app.route("/reports/accounting")
def accounting_reports():
    """Render the accounting reports page (Manager only)."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Get all accounting entries ordered by timestamp
    accounting_query = """
    SELECT timestamp, balance
    FROM AccountingTable
    ORDER BY timestamp DESC
    LIMIT 50;
    """
    accounting_data = execute_query(accounting_query, fetch_type='all')
    
    # Format the data for display
    accounting_entries = []
    previous_balance = None
    
    for i, entry in enumerate(accounting_data):
        timestamp = entry[0]
        balance = float(entry[1])
        
        # Calculate change from previous entry
        change = 0
        change_text = "N/A"
        change_class = ""
        
        if i < len(accounting_data) - 1:
            # Get the previous balance (which is the next entry in our descending list)
            previous_balance = float(accounting_data[i+1][1])
            change = balance - previous_balance
            
            if change > 0:
                change_text = f"+${change:.2f}"
                change_class = "positive-change"
            elif change < 0:
                change_text = f"-${abs(change):.2f}"
                change_class = "negative-change"
            else:
                change_text = "$0.00"
        
        accounting_entries.append({
            'date': timestamp.strftime('%Y-%m-%d'),
            'time': timestamp.strftime('%H:%M:%S'),
            'balance': balance,
            'change': change,
            'change_text': change_text,
            'change_class': change_class
        })
    
    # Get current balance (first entry from the descending ordered list)
    current_balance = float(accounting_data[0][1]) if accounting_data else 0.0
    
    return render_template(
        "accounting_reports.html", 
        accounting_entries=accounting_entries,
        current_balance=current_balance
    )


#==================================== Manager Additional reports ============================
# renders the revenue report webpage from the link on dashbaord having a form with other inputs
@app.route("/reports/revenue")
def revenue_report():
    """Render the revenue report page (Manager only)."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Just display the form initially
    return render_template("revenue_report.html")

# renders the details on filling out the form details for the report
@app.route("/reports/revenue", methods=["POST"])
def calculate_revenue():
    """Calculate revenue for a specified time period."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Check if the user is a manager
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Managers only.")
    
    # Get date range from form
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    
    if not start_date or not end_date:
        return render_template("error.html", message="Invalid date range provided.")
    
    try:
        # Convert string dates to datetime objects for database query
        # Add time component to make end_date inclusive
        start_datetime = f"{start_date} 00:00:00"
        end_datetime = f"{end_date} 23:59:59"
        
        # Calculate regular orders sales for the period
        sales_query = """
        SELECT COALESCE(SUM(total), 0) as total_sales, COUNT(*) as order_count
        FROM OrderTable
        WHERE timestamp BETWEEN %s AND %s;
        """
        sales_result = execute_query(sales_query, [start_datetime, end_datetime], 'one')
        regular_sales = float(sales_result[0]) if sales_result and sales_result[0] else 0.0
        regular_order_count = int(sales_result[1]) if sales_result and sales_result[1] else 0
        
        # Calculate ingredient costs for regular orders in the period
        ingredient_cost_query = """
        WITH OrderIngredients AS (
            -- Get all order details in the time period
            SELECT od.order_id, od.menu_id, od.quantity
            FROM OrderDetailTable od
            JOIN OrderTable o ON od.order_id = o.order_id
            WHERE o.timestamp BETWEEN %s AND %s
        ),
        -- Get all ingredients used in each menu item
        MenuIngredients AS (
            SELECT 
                r.menu_id,
                ip.ingredient_id,
                ip.quantity AS amount_per_item,
                i.price_per_unit
            FROM RecipeTable r
            JOIN PreparationStepsTable ps ON r.recipe_id = ps.recipe_id
            JOIN IngredientPreparationTable ip ON ps.prep_id = ip.prep_id
            JOIN IngredientTable i ON ip.ingredient_id = i.ingredient_id
        )
        -- Calculate total cost
        SELECT COALESCE(SUM(oi.quantity * mi.amount_per_item * mi.price_per_unit), 0) AS total_cost
        FROM OrderIngredients oi
        JOIN MenuIngredients mi ON oi.menu_id = mi.menu_id;
        """
        cost_result = execute_query(ingredient_cost_query, [start_datetime, end_datetime], 'one')
        regular_ingredient_costs = float(cost_result[0]) if cost_result and cost_result[0] else 0.0
        
        # Calculate promotion sales
        promo_sales_query = """
        SELECT 
            COALESCE(SUM(subtotal), 0) as promo_sales,
            COUNT(DISTINCT psd.order_id) as promo_order_count
        FROM PromotionSaleDetailTable psd
        JOIN OrderTable o ON psd.order_id = o.order_id
        WHERE o.timestamp BETWEEN %s AND %s;
        """
        promo_result = execute_query(promo_sales_query, [start_datetime, end_datetime], 'one')
        promo_sales = float(promo_result[0]) if promo_result and promo_result[0] else 0.0
        promo_order_count = int(promo_result[1]) if promo_result and promo_result[1] else 0
        
        # Calculate promotion ingredient costs
        promo_ingredient_cost_query = """
        WITH PromoOrders AS (
            -- Get all promotion sales in the time period
            SELECT psd.promotion_id, p.menu_id, psd.quantity
            FROM PromotionSaleDetailTable psd
            JOIN PromotionTable p ON psd.promotion_id = p.promotion_id
            JOIN OrderTable o ON psd.order_id = o.order_id
            WHERE o.timestamp BETWEEN %s AND %s
        ),
        -- Get all ingredients used in each menu item
        MenuIngredients AS (
            SELECT 
                r.menu_id,
                ip.ingredient_id,
                ip.quantity AS amount_per_item,
                i.price_per_unit
            FROM RecipeTable r
            JOIN PreparationStepsTable ps ON r.recipe_id = ps.recipe_id
            JOIN IngredientPreparationTable ip ON ps.prep_id = ip.prep_id
            JOIN IngredientTable i ON ip.ingredient_id = i.ingredient_id
        )
        -- Calculate total cost
        SELECT COALESCE(SUM(po.quantity * mi.amount_per_item * mi.price_per_unit), 0) AS total_cost
        FROM PromoOrders po
        JOIN MenuIngredients mi ON po.menu_id = mi.menu_id;
        """
        promo_cost_result = execute_query(promo_ingredient_cost_query, [start_datetime, end_datetime], 'one')
        promo_ingredient_costs = float(promo_cost_result[0]) if promo_cost_result and promo_cost_result[0] else 0.0
        
        # Calculate totals
        total_sales = regular_sales + promo_sales
        ingredient_costs = regular_ingredient_costs + promo_ingredient_costs
        net_revenue = total_sales - ingredient_costs
        
        # Prepare revenue data for the template
        revenue_data = {
            'start_date': start_date,
            'end_date': end_date,
            'total_sales': total_sales,
            'regular_sales': regular_sales,
            'promo_sales': promo_sales,
            'ingredient_costs': ingredient_costs,
            'net_revenue': net_revenue,
            'regular_order_count': regular_order_count,
            'promo_order_count': promo_order_count
        }
        
        return render_template("revenue_report.html", revenue_data=revenue_data)
        
    except Exception as e:
        print(f"Error calculating revenue: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return render_template("error.html", message=f"Error calculating revenue: {str(e)}")

# renders the popular items report from a link from dashboard
@app.route("/reports/popular_items", methods=["GET", "POST"])
def popular_items():
    """Show top-k most popular items per month."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Only managers can access reports
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Manager role required.")
    
    results = []
    
    if request.method == "POST":
        # Get form data
        month = int(request.form.get("month"))
        year = int(request.form.get("year"))
        k = int(request.form.get("top_k"))
        
        # SQL query to get top-k most popular items for a specific month
        query = """
        SELECT m.name, m.type, m.size, SUM(od.quantity) as total_quantity
        FROM OrderDetailTable od
        JOIN MenuTable m ON od.menu_id = m.menu_id
        JOIN OrderTable o ON od.order_id = o.order_id
        WHERE EXTRACT(MONTH FROM o.timestamp) = %s
        AND EXTRACT(YEAR FROM o.timestamp) = %s
        GROUP BY m.name, m.type, m.size
        ORDER BY total_quantity DESC
        LIMIT %s;
        """
        
        results = execute_query(query, [month, year, k], 'all')
    
    # Get current year for the form default
    current_year = datetime.now().year
    
    return render_template("popular_items.html", results=results, current_year=current_year)

# renders the revenue drinks report
@app.route("/reports/revenue_drinks", methods=["GET", "POST"])
def revenue_drinks():
    """Show top-k revenue generating drinks for a time period."""
    if "ssn" not in session or "role" not in session:
        return redirect("/")
    
    # Only managers can access reports
    if session["role"] != "Manager":
        return render_template("error.html", message="Access denied. Manager role required.")
    
    results = []
    
    if request.method == "POST":
        # Get form data
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        k = int(request.form.get("top_k"))
        
        # SQL query to get top-k revenue generating drinks for a time period
        query = """
        SELECT m.name, m.type, m.size, 
               SUM(od.subtotal) as total_revenue,
               ROUND((SUM(od.subtotal) * 100.0 / 
                    (SELECT SUM(subtotal) FROM OrderDetailTable 
                     JOIN OrderTable ON OrderDetailTable.order_id = OrderTable.order_id
                     WHERE OrderTable.timestamp BETWEEN %s AND %s)
               ), 2) as revenue_percentage
        FROM OrderDetailTable od
        JOIN MenuTable m ON od.menu_id = m.menu_id
        JOIN OrderTable o ON od.order_id = o.order_id
        WHERE o.timestamp BETWEEN %s AND %s
        GROUP BY m.name, m.type, m.size
        ORDER BY total_revenue DESC
        LIMIT %s;
        """
        
        results = execute_query(query, [start_date, end_date, start_date, end_date, k], 'all')
    
    return render_template("revenue_drinks.html", results=results)




def init_db():
    """Initialize database tables if they don't exist."""
    # Table creation queries
    tables = [
        '''CREATE TABLE IF NOT EXISTS EmployeeTable (
            ssn NUMERIC(9,0) NOT NULL CHECK(LENGTH(ssn::TEXT) = 9),
            role VARCHAR(50) NOT NULL,
            name VARCHAR(50) NOT NULL,
            email VARCHAR(255) NOT NULL,
            salary NUMERIC(10,2) NOT NULL CHECK(salary > 0),
            password VARCHAR(50) NOT NULL,
            PRIMARY KEY (ssn, role)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS ManagerTable (
            ssn NUMERIC(9,0) NOT NULL CHECK(LENGTH(ssn::TEXT) = 9),
            role VARCHAR(50) NOT NULL CHECK (role = 'Manager'),
            ownership_percent NUMERIC(5,2) NOT NULL,
            PRIMARY KEY (ssn, role),
            FOREIGN KEY (ssn, role) REFERENCES EmployeeTable (ssn, role) ON DELETE CASCADE ON UPDATE CASCADE
        );''',
        
        '''CREATE TABLE IF NOT EXISTS BaristaTable (
            ssn NUMERIC(9,0) NOT NULL CHECK(LENGTH(ssn::TEXT) = 9),
            role VARCHAR(50) NOT NULL CHECK (role = 'Barista'),
            day VARCHAR(20) NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            PRIMARY KEY (ssn, role, day, start_time),
            FOREIGN KEY (ssn, role) REFERENCES EmployeeTable (ssn, role) ON DELETE CASCADE ON UPDATE CASCADE
        );''',
        
        '''CREATE TABLE IF NOT EXISTS MenuTable(
            menu_id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            type VARCHAR(50) NOT NULL,
            temp VARCHAR(20) NOT NULL,
            size VARCHAR(20) NOT NULL,
            price NUMERIC(4, 2) NOT NULL CHECK (price >= 0)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS IngredientTable(
            ingredient_id SERIAL PRIMARY KEY,
            ingredient_name VARCHAR(80) NOT NULL,
            unit VARCHAR(20) NOT NULL,
            price_per_unit NUMERIC(6, 2) CHECK (price_per_unit > 0),
            amount_in_stock NUMERIC(8,2) CHECK (amount_in_stock >= 0)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS OrderTable(
            order_id SERIAL PRIMARY KEY,
            payment_method VARCHAR(50) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            total NUMERIC(6,2) NOT NULL CHECK(total >= 0)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS OrderDetailTable(
            order_detail_id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES OrderTable(order_id),
            menu_id INT NOT NULL REFERENCES MenuTable(menu_id),
            quantity INT NOT NULL CHECK(quantity > 0),
            subtotal NUMERIC(6,2) NOT NULL CHECK (subtotal >= 0)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS PromotionTable(
            promotion_id SERIAL PRIMARY KEY,
            promotion_name VARCHAR(80) NOT NULL,
            menu_id INT NOT NULL REFERENCES MenuTable(menu_id),
            promotion_quantity INT NOT NULL CHECK (promotion_quantity > 0),
            promotion_price NUMERIC(6,2) NOT NULL CHECK (promotion_price > 0),
            promotion_start_time TIMESTAMP NOT NULL,
            promotion_end_time TIMESTAMP NOT NULL,
            promotion_description TEXT
        );''',
        
        '''CREATE TABLE IF NOT EXISTS PromotionSaleDetailTable(
            promotion_sale_detail_id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES OrderTable(order_id),
            promotion_id INT NOT NULL REFERENCES PromotionTable(promotion_id),
            quantity INT NOT NULL CHECK (quantity > 0),
            subtotal NUMERIC(6, 2) NOT NULL CHECK (subtotal >= 0)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS RecipeTable(
            recipe_id SERIAL PRIMARY KEY,
            menu_id INT REFERENCES MenuTable(menu_id) NOT NULL
        );''',
        
        '''CREATE TABLE IF NOT EXISTS PreparationStepsTable(
            prep_id SERIAL PRIMARY KEY,
            recipe_id INT REFERENCES RecipeTable(recipe_id) NOT NULL,
            step_number INT NOT NULL CHECK(step_number > 0),
            description VARCHAR(255) NOT NULL
        );''',
        
        '''CREATE TABLE IF NOT EXISTS IngredientPreparationTable(
            ingredient_id INT REFERENCES IngredientTable(ingredient_id) NOT NULL,
            prep_id INT REFERENCES PreparationStepsTable(prep_id) NOT NULL,
            quantity NUMERIC(10, 2) NOT NULL CHECK (quantity > 0),
            PRIMARY KEY (ingredient_id, prep_id)
        );''',
        
        '''CREATE TABLE IF NOT EXISTS AccountingTable(
            timestamp TIMESTAMP PRIMARY KEY,
            balance NUMERIC(6,2) NOT NULL
        );'''
    ]
    
    # Create all tables
    for table_query in tables:
        execute_query(table_query)

if __name__ == '__main__':
    init_db()  # Initialize database tables
    app.secret_key = 'your_secret_key'  # Needed for session support
    app.run(debug=True)
import unittest
import threading
import time

# Monkey-patch network functions so no UDP calls occur during testing.
import network
network.send_order = lambda order: None
network.send_trade = lambda buy_id, sell_id, trade_price, trade_qty: None
network.send_cancel = lambda order: None
network.send_cancel_ack = lambda order: None
network.send_edit_ack = lambda order: None

# Import our modules under test.
from order_book import OrderBook, Order
from matching_engine import MatchingEngine
from utils import current_timestamp_ns  # If needed for time stamping

class TestOrderBookACID(unittest.TestCase):
    def setUp(self):
        # Create a new order book and matching engine for each test.
        self.order_book = OrderBook()
        self.engine = MatchingEngine(self.order_book)

    def process_order_thread(self, side, price, quantity, result_container, index):
        """
        Helper function to process an order in a thread.
        Stores the result (None for fully executed, or an Order object for a remainder)
        in result_container at the given index.
        """
        res = self.engine.process_order(side, price, quantity, owner=None)
        result_container[index] = res

    def test_sequential_processing_acid(self):
        """
        Test that while two orders are processed concurrently, the matching engine's lock
        ensures that the order book is updated completely for one order before the next order
        is processed (ACID property).
        
        Scenario:
          - Place a sell order (resting order) with quantity 10 at price 100.0.
          - Launch two threads that submit buy orders (each quantity 4, price 110.0).
          - Expectation: the first buy order will fully match 4 units of the sell order,
            updating its quantity from 10 to 6. Then the second buy order will match another 4,
            leaving the sell order with quantity 2.
        """
        # Place a resting sell order.
        sell_order = self.order_book.add_order("S", 100.0, 10)
        
        # Prepare two buy orders; use a container to store the result from each thread.
        results = [None, None]
        thread1 = threading.Thread(target=self.process_order_thread, args=("B", 110.0, 4, results, 0))
        thread2 = threading.Thread(target=self.process_order_thread, args=("B", 110.0, 4, results, 1))
        
        # Start both threads nearly simultaneously.
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()
        
        # After both orders are processed, the sell order should have quantity = 10 - 4 - 4 = 2.
        best_ask, total_qty = self.order_book.get_best_ask()
        self.assertEqual(best_ask, 100.0, "Best ask price should remain 100.0")
        self.assertEqual(total_qty, 2, "Remaining quantity should be 2 after two buy orders")
        
        # For fully matched incoming orders, process_order returns None.
        self.assertTrue(all(result is None for result in results),
                        "Both buy orders should have been fully executed (result is None)")
        
    def test_partial_and_full_fill(self):
        """Test a scenario with a partial fill followed by a full fill."""
        # Place a sell order of quantity 10.
        sell_order = self.order_book.add_order("S", 100.0, 10)
        # Place a buy order of quantity 6 to partially fill the sell order.
        res1 = self.engine.process_order("B", 110.0, 6)
        # Expect res1 to be None (fully matched incoming order) and the sell order to be updated.
        self.assertIsNone(res1)
        updated_sell = self.order_book.orders_by_id.get(sell_order.id)
        self.assertIsNotNone(updated_sell)
        self.assertEqual(updated_sell.quantity, 4, "Sell order should have 4 units remaining")
        # Now place a buy order for 4 units to fully fill the remaining sell order.
        res2 = self.engine.process_order("B", 110.0, 4)
        self.assertIsNone(res2)
        self.assertNotIn(sell_order.id, self.order_book.orders_by_id,
                         "Sell order should be removed after full fill")

    def test_edit_and_cancel(self):
        """Test order editing and cancellation functionality."""
        # Place a buy order.
        order = self.order_book.add_order("B", 99.0, 10)
        # Edit the order.
        success_edit = self.order_book.edit_order(order.id, new_price=100.0, new_quantity=15)
        self.assertTrue(success_edit, "Order edit should succeed")
        edited_order = self.order_book.orders_by_id.get(order.id)
        self.assertEqual(edited_order.price, 100.0)
        self.assertEqual(edited_order.quantity, 15)
        # Cancel the order.
        success_cancel = self.order_book.cancel_order(order.id)
        self.assertTrue(success_cancel, "Order cancellation should succeed")
        self.assertNotIn(order.id, self.order_book.orders_by_id,
                         "Order should be removed from the book after cancellation")
        # Attempt to edit the cancelled order.
        success_edit_after_cancel = self.order_book.edit_order(order.id, new_price=102.0, new_quantity=5)
        self.assertFalse(success_edit_after_cancel, "Editing a cancelled order should fail")

    def test_multiple_fill_aggregation(self):
        """Test that an incoming order matching multiple resting orders is processed correctly."""
        # Create two sell orders at the same price.
        sell_order1 = self.order_book.add_order("S", 100.0, 5)
        sell_order2 = self.order_book.add_order("S", 100.0, 10)
        # Place a buy order for 12 units. It should fully fill sell_order1 (5 units) and partially fill sell_order2 (7 units).
        res = self.engine.process_order("B", 110.0, 12)
        self.assertIsNone(res)
        # sell_order1 should be removed.
        self.assertNotIn(sell_order1.id, self.order_book.orders_by_id)
        # sell_order2 should remain with 3 units (10 - 7).
        updated_sell2 = self.order_book.orders_by_id.get(sell_order2.id)
        self.assertIsNotNone(updated_sell2)
        self.assertEqual(updated_sell2.quantity, 3)

if __name__ == '__main__':
    unittest.main()

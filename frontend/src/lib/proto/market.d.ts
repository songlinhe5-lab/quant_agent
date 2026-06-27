import * as $protobuf from "protobufjs";
import Long = require("long");
/** Namespace market. */
export namespace market {

    /** Properties of an Order. */
    interface IOrder {

        /** Order price */
        price?: (number|null);

        /** Order size */
        size?: (number|null);
    }

    /** Represents an Order. */
    class Order implements IOrder {

        /**
         * Constructs a new Order.
         * @param [properties] Properties to set
         */
        constructor(properties?: market.IOrder);

        /** Order price. */
        public price: number;

        /** Order size. */
        public size: number;

        /**
         * Creates a new Order instance using the specified properties.
         * @param [properties] Properties to set
         * @returns Order instance
         */
        public static create(properties?: market.IOrder): market.Order;

        /**
         * Encodes the specified Order message. Does not implicitly {@link market.Order.verify|verify} messages.
         * @param message Order message or plain object to encode
         * @param [writer] Writer to encode to
         * @returns Writer
         */
        public static encode(message: market.IOrder, writer?: $protobuf.Writer): $protobuf.Writer;

        /**
         * Encodes the specified Order message, length delimited. Does not implicitly {@link market.Order.verify|verify} messages.
         * @param message Order message or plain object to encode
         * @param [writer] Writer to encode to
         * @returns Writer
         */
        public static encodeDelimited(message: market.IOrder, writer?: $protobuf.Writer): $protobuf.Writer;

        /**
         * Decodes an Order message from the specified reader or buffer.
         * @param reader Reader or buffer to decode from
         * @param [length] Message length if known beforehand
         * @returns Order
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        public static decode(reader: ($protobuf.Reader|Uint8Array), length?: number): market.Order;

        /**
         * Decodes an Order message from the specified reader or buffer, length delimited.
         * @param reader Reader or buffer to decode from
         * @returns Order
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        public static decodeDelimited(reader: ($protobuf.Reader|Uint8Array)): market.Order;

        /**
         * Verifies an Order message.
         * @param message Plain object to verify
         * @returns `null` if valid, otherwise the reason why it is not
         */
        public static verify(message: { [k: string]: any }): (string|null);

        /**
         * Creates an Order message from a plain object. Also converts values to their respective internal types.
         * @param object Plain object
         * @returns Order
         */
        public static fromObject(object: { [k: string]: any }): market.Order;

        /**
         * Creates a plain object from an Order message. Also converts values to other types if specified.
         * @param message Order
         * @param [options] Conversion options
         * @returns Plain object
         */
        public static toObject(message: market.Order, options?: $protobuf.IConversionOptions): { [k: string]: any };

        /**
         * Converts this Order to JSON.
         * @returns JSON object
         */
        public toJSON(): { [k: string]: any };

        /**
         * Gets the default type url for Order
         * @param [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns The default type url
         */
        public static getTypeUrl(typeUrlPrefix?: string): string;
    }

    /** Properties of a QuoteData. */
    interface IQuoteData {

        /** QuoteData status */
        status?: (string|null);

        /** QuoteData ticker */
        ticker?: (string|null);

        /** QuoteData lastPrice */
        lastPrice?: (number|null);

        /** QuoteData changePct */
        changePct?: (string|null);

        /** QuoteData volumeStr */
        volumeStr?: (string|null);

        /** QuoteData bids */
        bids?: (market.IOrder[]|null);

        /** QuoteData asks */
        asks?: (market.IOrder[]|null);

        /** QuoteData source */
        source?: (string|null);
    }

    /** Represents a QuoteData. */
    class QuoteData implements IQuoteData {

        /**
         * Constructs a new QuoteData.
         * @param [properties] Properties to set
         */
        constructor(properties?: market.IQuoteData);

        /** QuoteData status. */
        public status: string;

        /** QuoteData ticker. */
        public ticker: string;

        /** QuoteData lastPrice. */
        public lastPrice: number;

        /** QuoteData changePct. */
        public changePct: string;

        /** QuoteData volumeStr. */
        public volumeStr: string;

        /** QuoteData bids. */
        public bids: market.IOrder[];

        /** QuoteData asks. */
        public asks: market.IOrder[];

        /** QuoteData source. */
        public source: string;

        /**
         * Creates a new QuoteData instance using the specified properties.
         * @param [properties] Properties to set
         * @returns QuoteData instance
         */
        public static create(properties?: market.IQuoteData): market.QuoteData;

        /**
         * Encodes the specified QuoteData message. Does not implicitly {@link market.QuoteData.verify|verify} messages.
         * @param message QuoteData message or plain object to encode
         * @param [writer] Writer to encode to
         * @returns Writer
         */
        public static encode(message: market.IQuoteData, writer?: $protobuf.Writer): $protobuf.Writer;

        /**
         * Encodes the specified QuoteData message, length delimited. Does not implicitly {@link market.QuoteData.verify|verify} messages.
         * @param message QuoteData message or plain object to encode
         * @param [writer] Writer to encode to
         * @returns Writer
         */
        public static encodeDelimited(message: market.IQuoteData, writer?: $protobuf.Writer): $protobuf.Writer;

        /**
         * Decodes a QuoteData message from the specified reader or buffer.
         * @param reader Reader or buffer to decode from
         * @param [length] Message length if known beforehand
         * @returns QuoteData
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        public static decode(reader: ($protobuf.Reader|Uint8Array), length?: number): market.QuoteData;

        /**
         * Decodes a QuoteData message from the specified reader or buffer, length delimited.
         * @param reader Reader or buffer to decode from
         * @returns QuoteData
         * @throws {Error} If the payload is not a reader or valid buffer
         * @throws {$protobuf.util.ProtocolError} If required fields are missing
         */
        public static decodeDelimited(reader: ($protobuf.Reader|Uint8Array)): market.QuoteData;

        /**
         * Verifies a QuoteData message.
         * @param message Plain object to verify
         * @returns `null` if valid, otherwise the reason why it is not
         */
        public static verify(message: { [k: string]: any }): (string|null);

        /**
         * Creates a QuoteData message from a plain object. Also converts values to their respective internal types.
         * @param object Plain object
         * @returns QuoteData
         */
        public static fromObject(object: { [k: string]: any }): market.QuoteData;

        /**
         * Creates a plain object from a QuoteData message. Also converts values to other types if specified.
         * @param message QuoteData
         * @param [options] Conversion options
         * @returns Plain object
         */
        public static toObject(message: market.QuoteData, options?: $protobuf.IConversionOptions): { [k: string]: any };

        /**
         * Converts this QuoteData to JSON.
         * @returns JSON object
         */
        public toJSON(): { [k: string]: any };

        /**
         * Gets the default type url for QuoteData
         * @param [typeUrlPrefix] your custom typeUrlPrefix(default "type.googleapis.com")
         * @returns The default type url
         */
        public static getTypeUrl(typeUrlPrefix?: string): string;
    }
}
